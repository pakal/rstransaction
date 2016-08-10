#!/usr/bin/env python
# -*- coding: utf-8 -*-


import sys
import os
import shutil
import stat
import random
import time
import unittest
import collections

import rstransaction.transaction_processor as TP
from rstransaction.transaction_processor import TransactionWorkflowError, TransactionRollbackFailure, TransactionRecordingFailure


class TestActionRecorderBase(unittest.TestCase):

    def setUp(self):
        self.recorder = TP.ActionRecorderBase("header string for disk log")

    def tearDown(self):
        pass

    def testActionRecorderBehaviour(self):
        rec = self.recorder

        self.assertTrue(rec.is_empty())
        self.assertEqual(rec.get_action_count(), 0)
        self.assertRaises(TransactionWorkflowError, rec.last_action_is_finished)

        self.assertEqual(rec.get_savepoint_count(), 0)
        self.assertRaises(TransactionWorkflowError, rec.get_action_count_since_last_savepoint)
        self.assertRaises(TransactionWorkflowError, rec.commit_last_savepoint)
        self.assertRaises(TransactionWorkflowError, rec.rollback_last_savepoint)

        rec.create_savepoint()
        rec.create_savepoint()  # savepoint committed remotely
        self.assertEqual(rec.get_savepoint_count(), 2)
        self.assertEqual(rec.get_action_count_since_last_savepoint(), 0)

        rec.begin_action_processing("beginAction1")
        self.assertRaises(TransactionWorkflowError, rec.begin_action_processing, None)
        rec.finish_action_processing("endAction1")
        self.assertRaises(TransactionWorkflowError, rec.finish_action_processing, None)
        rec.begin_action_processing("beginAction2")

        self.assertRaises(TransactionWorkflowError, rec.create_savepoint)
        self.assertRaises(TransactionWorkflowError, rec.commit_last_savepoint)
        self.assertRaises(TransactionWorkflowError, rec.rollback_last_savepoint)
        self.assertEqual(rec.get_savepoint_count(), 2)
        self.assertEqual(rec.get_action_count_since_last_savepoint(), 2)

        self.assertFalse(rec.is_empty())
        self.assertEqual(rec.get_action_count(), 2)
        self.assertFalse(rec.last_action_is_finished())
        self.assertRaises(TransactionWorkflowError, rec.get_finished_action)
        self.assertRaises(TransactionWorkflowError, rec.rollback_finished_action)
        self.assertEqual(rec.get_unfinished_action(), "beginAction2")

        rec.rollback_unfinished_action()

        self.assertFalse(rec.is_empty())
        self.assertEqual(rec.get_action_count(), 1)
        self.assertTrue(rec.last_action_is_finished())
        self.assertRaises(TransactionWorkflowError, rec.get_unfinished_action)
        self.assertRaises(TransactionWorkflowError, rec.rollback_unfinished_action)

        rec.create_savepoint()
        rec.rollback_last_savepoint()
        rec.create_savepoint()
        rec.commit_last_savepoint()
        rec.commit_last_savepoint()  # commits the remote savepoint above
        self.assertEqual(rec.get_savepoint_count(), 1)
        self.assertEqual(rec.get_action_count_since_last_savepoint(), 1)

        self.assertEqual(rec.get_finished_action(), ("beginAction1", "endAction1"))

        rec.rollback_finished_action()

        self.assertRaises(TransactionWorkflowError, rec.commit_transaction)  # one savepoint is left

        rec.rollback_last_savepoint()
        self.assertEqual(rec.get_savepoint_count(), 0)

        rec.begin_action_processing("beginAction1")
        self.assertRaises(TransactionWorkflowError, rec.commit_transaction)  # one action is unfinished
        rec.finish_action_processing("endAction1")
        rec.commit_transaction()  # this time is shall work

        self.assertTrue(rec.is_empty())
        self.assertEqual(rec.get_action_count(), 0)
        self.assertRaises(TransactionWorkflowError, rec.last_action_is_finished)
        self.assertRaises(TransactionWorkflowError, rec.get_finished_action)
        self.assertRaises(TransactionWorkflowError, rec.rollback_finished_action)
        self.assertRaises(TransactionWorkflowError, rec.get_unfinished_action)
        self.assertRaises(TransactionWorkflowError, rec.rollback_unfinished_action)


class TestActionRegistry(unittest.TestCase):

    def testRegistries(self):

        with TP.recording_failure_handler():
            _ = "nothing happens"
        with self.assertRaises(TransactionRecordingFailure):
            with TP.recording_failure_handler():
                raise ValueError("tralalal")

        action1 = TP.TransactionalActionAdapter(lambda: "process1", lambda w, x, y, z: "rollback1")
        action2 = TP.TransactionalActionAdapter(lambda: "process2", lambda w, x, y, z: "rollback2", lambda: ((), {}))

        tb = TP.TransactionalActionRegistry(action1=action1, action2=action2)
        self.assertRaises(ValueError, TP.TransactionalActionRegistry, tb, action1=action1)
        self.assertRaises(ValueError, TP.TransactionalActionRegistry, _action1=action1)
        self.assertRaises(ValueError, TP.TransactionalActionRegistry, tx_action1=action1)

        tb.register_action("action0", action1)
        self.assertRaises(ValueError, tb.register_action, "_action", action1)
        self.assertRaises(ValueError, tb.register_action, "tx_action", action1)
        self.assertRaises(ValueError, tb.register_action, "action1", action1)  # duplicate
        self.assertEqual(sorted(tb.list_registered_actions()), ['action0', 'action1', 'action2'])

        tb.unregister_action("action1")

        self.assertEqual(sorted(tb.list_registered_actions()), ['action0', 'action2'])

        tb_merge = TP.TransactionalActionRegistry(tb, action1=action1)
        self.assertEqual(sorted(tb_merge.list_registered_actions()), ['action0', 'action1', 'action2'])

        self.assertEqual(tb_merge.get_action('action1'), action1)

        tb_merge.unregister_action("action0")
        tb_merge.unregister_action("action1")

        self.assertEqual(tb_merge.list_registered_actions(), ['action2'])
        self.assertEqual(tb_merge.get_registry(), {'action2': action2})

        with self.assertRaises(ValueError):
            tb.unregister_action("unexisting_action")
        with self.assertRaises(ValueError):
            tb.get_action("unexisting_action")


class TestTransactionBase(unittest.TestCase):

    def setUp(self):

        def failure():
            raise ZeroDivisionError("Boooh")
        self.registry = TP.TransactionalActionRegistry()
        self.registry.register_action(
            "action_success", TP.TransactionalActionAdapter(
                lambda: "no problem here", lambda w, x, y, z: None))
        self.registry.register_action("action_bad_preprocess", TP.TransactionalActionAdapter(
            lambda x: "no problem too", lambda w, x, y, z: None, lambda: ((failure(),), {})))
        self.registry.register_action(
            "action_failure", TP.TransactionalActionAdapter(
                lambda x, y: failure(), lambda w, x, y, z: None))
        self.registry.register_action(
            "action_failure_unfixable", TP.TransactionalActionAdapter(
                lambda x, y: failure(), lambda w, x, y, z: failure()))

        self.recorder = TP.ActionRecorderBase()
        self.transaction_base = TP.TransactionBase(self.registry, self.recorder)

    def tearDown(self):
        pass

    def testOneStepMethods(self):

        rec = self.recorder
        tb = self.transaction_base

        # we check that magic attribute handling works well
        self.assertTrue(isinstance(tb.action_success, collections.Callable))
        self.assertRaises(AttributeError, getattr, tb, "unexisting_action_name")

        # we check that public methods are well abstract
        self.assertRaises(NotImplementedError, tb.tx_process_action, "dummy action name")
        self.assertRaises(NotImplementedError, tb.tx_rollback)
        self.assertRaises(NotImplementedError, tb.tx_commit)
        self.assertRaises(NotImplementedError, tb.tx_create_savepoint)
        self.assertRaises(NotImplementedError, tb.tx_rollback_savepoint)
        self.assertRaises(NotImplementedError, tb.tx_commit_savepoint)

        # one action which works
        self.assertEqual(tb._execute_selected_action("action_success"), "no problem here")
        self.assertTrue(rec.last_action_is_finished())
        self.assertEqual(rec.get_action_count(), 1)
        self.assertEqual(rec.get_finished_action(), (("action_success", (), {}), "no problem here"))

        # one action which fails during preprocessing
        self.assertRaises(ZeroDivisionError, tb._execute_selected_action, "action_bad_preprocess")
        self.assertTrue(rec.last_action_is_finished())
        self.assertEqual(rec.get_action_count(), 1)

        # one action which fails during processing itself
        self.assertRaises(ZeroDivisionError, tb._execute_selected_action,
                          "action_failure", ("myarg1",), {"y": "myarg2"})
        self.assertFalse(rec.last_action_is_finished())
        self.assertEqual(rec.get_action_count(), 2)
        self.assertEqual(rec.get_unfinished_action(), ("action_failure", ("myarg1",), {"y": "myarg2"}))

        # we check that in this case the return-to-consistent-state operation works
        self.assertEqual(tb._rollback_to_last_consistent_state(), True)
        self.assertEqual(tb._rollback_to_last_consistent_state(), False)  # no-op this time
        self.assertEqual(rec.get_action_count(), 1)
        self.assertTrue(rec.last_action_is_finished())

        # we test the totally failing action, which leads to a persistent inconsistent state
        self.assertRaises(ZeroDivisionError, tb._execute_selected_action,
                          "action_failure_unfixable", ("myarg1",), {"y": "myarg2"})
        self.assertRaises(ZeroDivisionError, tb._rollback_to_last_consistent_state)
        self.assertEqual(rec.get_action_count(), 2)
        self.assertFalse(rec.last_action_is_finished())

    def testLargeMethods(self):

        rec = self.recorder
        tb = self.transaction_base

        self.assertEqual(rec.get_action_count(), 0)
        tb._execute_selected_action("action_success")
        rec.create_savepoint()
        tb._execute_selected_action("action_success")
        self.assertRaises(ZeroDivisionError, tb._execute_selected_action,
                          "action_failure", ("myarg1",), {"y": "myarg2"})
        self.assertRaises(TransactionWorkflowError, tb._commit_consistent_transaction)
        self.assertRaises(TransactionWorkflowError, tb._rollback_consistent_transaction)

        tb._rollback_to_last_consistent_state()
        tb._rollback_consistent_transaction(rollback_to_last_savepoint=True)
        rec.rollback_last_savepoint()
        self.assertEqual(rec.get_action_count(), 1)
        self.assertRaises(
            TransactionWorkflowError,
            tb._rollback_consistent_transaction,
            rollback_to_last_savepoint=True)
        tb._rollback_consistent_transaction()
        self.assertEqual(rec.get_action_count(), 0)

        tb._execute_selected_action("action_success")
        self.assertEqual(rec.get_action_count(), 1)
        tb._commit_consistent_transaction()
        self.assertEqual(rec.get_action_count(), 0)

        rec.create_savepoint()
        self.assertRaises(TransactionWorkflowError, tb._rollback_consistent_transaction)  # savepoint blocks it


class TestInteractiveTransaction(unittest.TestCase):

    def setUp(self):

        self.DEPOT = DEPOT = []

        def transform(number):
            assert isinstance(number, int)
            return (str(number), len(DEPOT)), {}

        def transform_fail(number):
            raise ValueError("dummy preprocessing error")

        def add_word(word, initial_size):
            DEPOT.append(word)
            return len(DEPOT)

        def add_word_fail(word, initial_size):
            raise ValueError("add_word_fail")

        def add_word_random_fail(word, initial_size):
            if not random.randint(0, 2):
                raise ValueError("add_word_random_fail")
            res = add_word(word, initial_size)
            if not random.randint(0, 2):
                raise IOError("add_word_random_fail")
            return res

        def _remove_word(word, initial_size):
            if len(DEPOT) == initial_size + 1:
                assert DEPOT[-1] == word
                DEPOT.pop()
            else:
                assert len(DEPOT) == initial_size
                pass  # operation was interrupted before completing

        def rollback_word(args, kwargs, was_interrupted, result=None):
            if not was_interrupted:
                assert len(DEPOT) == result
            _remove_word(*args, **kwargs)

        def rollback_word_fail(args, kwargs, was_interrupted, result=None):
            raise RuntimeError("dummy impossible rollback")

        self.registry = TP.TransactionalActionRegistry()

        self.registry.register_action("action_success",
                                      TP.TransactionalActionAdapter(add_word, rollback_word,
                                                                    preprocess_arguments=transform))

        self.registry.register_action("action_bad_preprocess",
                                      TP.TransactionalActionAdapter(add_word, rollback_word,
                                                                    preprocess_arguments=transform_fail))

        self.registry.register_action("action_random_failure",
                                      TP.TransactionalActionAdapter(add_word_random_fail, rollback_word,
                                                                    preprocess_arguments=transform))

        self.registry.register_action("action_failure_unfixable",
                                      TP.TransactionalActionAdapter(add_word_fail, rollback_word_fail,
                                                                    preprocess_arguments=transform))

        self.recorder = TP.ActionRecorderBase()
        self.tp = TP.InteractiveTransaction(self.registry, self.recorder)

    def tearDown(self):
        pass

    def testWholeInteractiveTransaction(self):

        tp = self.tp  # interactive transaction processor

        with tp:
            tp.tx_process_action("action_success", 1)
            with self.assertRaises(TransactionWorkflowError):
                with tp:  # can't nest transactions, use savepoint!
                    pass  

        assert self.DEPOT == ["1"], self.DEPOT
        
        with self.assertRaises(IOError):
            with tp:
                tp.tx_process_action("action_success", 222)
                raise IOError("abort TP")

        assert self.DEPOT == ["1"], self.DEPOT
            
        with tp.tx_savepoint():
            tp.tx_process_action("action_success", number=66)

        assert self.DEPOT == ["1", "66"], self.DEPOT

        with self.assertRaises(ValueError):

            with tp.tx_savepoint():

                tp.tx_process_action("action_success", number=201)

                assert self.DEPOT == ["1", "66", "201"], self.DEPOT

                tp.tx_process_action("action_bad_preprocess", number=404)

        assert self.DEPOT == ["1", "66"], self.DEPOT  # well rolled back to savepoint

        tp.tx_process_action("action_success", number=12)

        assert self.DEPOT == ["1", "66", "12"], self.DEPOT

        tp.tx_commit()

        assert self.DEPOT == ["1", "66", "12"], self.DEPOT

        tp.tx_rollback()

        assert self.DEPOT == ["1", "66", "12"], self.DEPOT  # unchanged

        tp.tx_process_action("action_success", number=55)

        assert self.DEPOT == ["1", "66", "12", "55"], self.DEPOT

        tp.tx_rollback()

        assert self.DEPOT == ["1", "66", "12"], self.DEPOT  # reverted to last COMMIT point

        tp.tx_process_action("action_success", number=55)

        assert self.DEPOT == ["1", "66", "12", "55"], self.DEPOT

        with self.assertRaises((IOError, ValueError)):
            while True:
                tp.tx_process_action("action_random_failure", number=13)

        assert self.DEPOT != ["1", "66", "12"], self.DEPOT

        with self.assertRaises(TransactionWorkflowError):
            tp.tx_process_action("action_success", number=888)
        with self.assertRaises(TransactionWorkflowError):
            tp.tx_commit()
        tp.tx_rollback()

        assert self.DEPOT == ["1", "66", "12"], self.DEPOT

        with self.assertRaises(ValueError):
            tp.tx_process_action("action_failure_unfixable", number=44)
        with self.assertRaises(TransactionWorkflowError):
            tp.tx_commit()
        with self.assertRaises(TransactionRollbackFailure):
            tp.tx_rollback()
   


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testCall']
    unittest.main()
