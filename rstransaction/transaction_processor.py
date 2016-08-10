#!/usr/bin/env python
# -*- coding: utf-8 -*-


import sys
import os
import functools
from contextlib import contextmanager


class TransactionFailure(Exception):
    pass


class TransactionWorkflowError(TransactionFailure):
    pass


class TransactionRecordingFailure(TransactionFailure):
    pass


class TransactionRollbackFailure(TransactionFailure):
    pass


@contextmanager
def recording_failure_handler():
    "Rewrites outgoing exceptions as TransactionRecordingFailure"
    try:
        yield
    except Exception as e:
        raise TransactionRecordingFailure(repr(e))


class TransactionalActionBase(object):
    """
    This abstract class defines the interface and semantic of "transactional action" objects.
    """

    def preprocess_arguments(self, *args, **kwargs):
        """
        Method called just before executing the action.
        Its only role is to transform the arguments received by the action,
        into a set of context-independent parameters (maybe with the help of instance-specific
        attributes), which fully determine what the action will do.
        For example, such a treatment might transform relative path into absolute ones,
        and determine the resources needed to perform the action in an "undo-able" way.
        The tuple (args, kwargs) that this method returns will be recorded, and expanded
        in input (i.e *args and **kwargs) to :meth:`process_action` and :meth:`rollback_action`.
        """
        return (args, kwargs)

    @staticmethod
    def process_action(*args, **kwargs):
        """
        This static method receives preprocessed arguments in input, and
        shall perform the transactional action it represents, returning its result (if any).
        Any error preventing the success of this action shall simply be left propagating, so
        that upper level transactional structures can take measures accordingly (:meth:`rollback_action`
        shall not be directly called by this method).
        Note that the signature and return type of this method are free, as long as expected arguments
        match the output of the potential :meth:`preprocess_arguments` method.
        """
        raise NotImplementedError()

    @staticmethod
    def rollback_action(args, kwargs, was_interrupted, result=None):
        """
        This static method shall determine and undo all the changes made by a previous
        :meth:`process_action` call.
        If :meth:`process_action` was interrupted by a crash or an exception, *was_interrupted*
        is True, and *result* is None. Else, result is the value (if any) which was returned by the
        meth:`process_action` call - this might be an appreciable hint in some circumstances.
        In any case, args and kwargs are the list and dict which contain the arguments with which
        :meth:`process_action` was called.
        In case of trouble preventing the rollback, this method shall raise an exception.
        No return value is expected.
        """
        raise NotImplementedError()


_function_interrupted = object()


class TransactionalActionAdapter(TransactionalActionBase):
    """
    This class provides a handy way of creating transactional action instances.
    Instead of subclassing :class:`TransactionalActionBase`, you may simply instanciate
    this class by providing process_action and rollback_action callables (with potentially a
    preprocess_arguments one, which must NOT expect 'self' as first argument).
    The resulting object will behave like the instance of a subclass of :class:`TransactionalActionBase`,
    which would have overriden necessary methods.
    """

    def __init__(self, process_action, rollback_action, preprocess_arguments=None):

        assert process_action and rollback_action

        self._preprocess_arguments = preprocess_arguments
        self._process_action = process_action
        self._rollback_action = rollback_action

    def preprocess_arguments(self, *args, **kwargs):
        if not self._preprocess_arguments:
            return (args, kwargs)  # default preprocessing : do nothing
        else:
            return self._preprocess_arguments(*args, **kwargs)

    def process_action(self, *args, **kwargs):
        return self._process_action(*args, **kwargs)

    def rollback_action(self, args, kwargs, was_interrupted, result=_function_interrupted):
        if not (was_interrupted and result is _function_interrupted) and not (
                not was_interrupted and not result is _function_interrupted):
            raise ValueError("Wrong argument combination for rollback_action")
        return self._rollback_action(args, kwargs, was_interrupted, result)


class TransactionalActionRegistry(object):

    def __init__(self, *source_action_registries, **initial_actions):

        # First, we check that no conflict will happen with the different names
        all_names = list(initial_actions.keys())
        for source in source_action_registries:
            all_names += source.list_registered_actions()
        if len(all_names) != len(set(all_names)):  # else, duplicate names found...
            raise ValueError("Duplicate action names inserted into registry")
        for name in all_names:
            self._check_action_name(name)

        # Now, we mix sources together
        self._registered_actions = initial_actions  # couples name->TransactionalActionBase
        for source in source_action_registries:
            self._registered_actions.update(source.get_registry())

    def _check_action_name(self, name):
        if name.startswith("_") or name.startswith("tx_"):  # we do not want conflicts with normal methods
            raise ValueError("Invalid action name %s" % name)

    def register_action(self, name, action):
        if name in self._registered_actions:
            raise ValueError("Already existing action %s" % name)
        self._check_action_name(name)
        self._registered_actions[name] = action

    def unregister_action(self, name):
        if name not in self._registered_actions:
            raise ValueError("Unxisting action %s" % name)
        del self._registered_actions[name]

    def list_registered_actions(self):
        return list(self._registered_actions.keys())

    def get_action(self, name):
        if name not in self._registered_actions:
            raise ValueError("Unxisting action name %s" % name)
        return self._registered_actions[name]

    def get_registry(self):
        return self._registered_actions


class ActionRecorderBase(object):

    _BEGIN_RECORD = 0
    _END_RECORD = 1

    def __init__(self, media_header=None):
        self._performed_actions_log = []
        self._savepoint_indexes = []  # sorted positions of different savepoints, as slice index values

        if media_header is not None:
            self._initialize_recorder_media(media_header)

    ### Methods to manage savepoints ###

    def create_savepoint(self):
        if not (self.is_empty() or self.last_action_is_finished()):  # no savepoint inside an unfinished action !
            raise TransactionWorkflowError("No savepoint creation allowed during an action processing")
        self._savepoint_indexes.append(len(self._performed_actions_log))  # not a problem if DUPLICATE savepoints!

    def get_savepoint_count(self):
        return len(self._savepoint_indexes)

    def get_action_count_since_last_savepoint(self):
        if not self.get_savepoint_count():
            raise TransactionWorkflowError("No existing savepoint")
        savepoint_position = self._savepoint_indexes[-1]
        records_concerned = len(self._performed_actions_log) - savepoint_position
        return int(records_concerned / 2 + records_concerned % 2)  # one of the actions might be unfinished...

    def commit_last_savepoint(self):
        if not (self.is_empty() or self.last_action_is_finished()):
            # no commit inside an unfinished action !
            raise TransactionWorkflowError("Cannot commit savepoint in inconsistent state")
        if not self.get_savepoint_count():
            raise TransactionWorkflowError("No savepoint to commit")
        del self._savepoint_indexes[-1]

    def rollback_last_savepoint(self):
        if not self.get_savepoint_count():
            raise TransactionWorkflowError("No savepoint to rollback to")
        if not (self._savepoint_indexes[-1] == len(self._performed_actions_log)):
            # we can only rollback the savepoint when following actions have been rolled back too
            raise TransactionWorkflowError(
                "Savepoint canot be rolled back before its subsequent actions are rolled back")
        del self._savepoint_indexes[-1]

    def _check_savepoints_integrity(self):
        if self.get_savepoint_count():
            # savepoints must not point beyond the action stack
            assert self._savepoint_indexes[-1] <= len(self._performed_actions_log)

    ### Methods to retrieve information of recorded actions ###

    def is_empty(self):
        return not self._performed_actions_log

    def get_action_count(self):
        # Returns both finished actions, and a potential unfinished last action
        return len([i for i in self._performed_actions_log if i[0] == self._BEGIN_RECORD])

    def last_action_is_finished(self):
        if self.is_empty():
            raise TransactionWorkflowError("No actions recorded yet")
        # WARNING - TO BE MODIFIED WHEN ADDING SAVEPOINTS
        if self._performed_actions_log and self._performed_actions_log[-1][0] == self._END_RECORD:
            return True
        return False  # This means that the last action is in UNFINISHED state

    ### Methods to process new actions ###

    def begin_action_processing(self, value):
        if (self._performed_actions_log and self._performed_actions_log[-1][0] != self._END_RECORD):
            raise TransactionWorkflowError("Improper begin_action_processing call")
        record = (self._BEGIN_RECORD, value)
        self._performed_actions_log.append(record)
        self._append_record_to_media(self._BEGIN_RECORD, value)

    def finish_action_processing(self, value):
        if (not self._performed_actions_log or self._performed_actions_log[-1][0] != self._BEGIN_RECORD):
            raise TransactionWorkflowError("Improper finish_action_processing call")
        record = (self._END_RECORD, value)
        self._performed_actions_log.append(record)
        self._append_record_to_media(self._END_RECORD, value)

    ### Methods to rollback a single action ###

    def get_unfinished_action(self):
        if (self.is_empty() or self.last_action_is_finished()):
            raise TransactionWorkflowError("No unfinished action in progress")
        return self._performed_actions_log[-1][1]

    def rollback_unfinished_action(self):
        if (self.is_empty() or self.last_action_is_finished()):
            raise TransactionWorkflowError("No unfinished action to rollback")
        self._performed_actions_log.pop()  # removes last element
        self._remove_last_record_from_media()
        if __debug__:
            self._check_savepoints_integrity()

    def get_finished_action(self):
        if (self.is_empty() or not self.last_action_is_finished()):
            raise TransactionWorkflowError("Current action is unfinished")
        return (self._performed_actions_log[-2][1], self._performed_actions_log[-1][1])

    def rollback_finished_action(self):
        if (self.is_empty() or not self.last_action_is_finished()):
            raise TransactionWorkflowError("No finished action to rollback")
        for _ in range(2):  # we pop the beginning and ending records
            self._performed_actions_log.pop()  # removes last element
            self._remove_last_record_from_media()
            if __debug__:
                self._check_savepoints_integrity()

    ### Method to finalize the recording ###

    def commit_transaction(self):
        if not (self.is_empty() or self.last_action_is_finished()):
            raise TransactionWorkflowError("Can't commit unfinished action")
        if self.get_savepoint_count():  # all savepoints must be rolled back or committed before !
            raise TransactionWorkflowError("Pending savepoints must be committed first")
        self._performed_actions_log = []  # full reinitialization, allowing further use of the transaction and recorder objects
        self._commit_transaction_to_media()

    ### Data persistence methods, to be overriden in subclasses ###
    def _initialize_recorder_media(self, value):
        pass

    def _append_record_to_media(self, record_type, value):
        pass  # there, save to DB or to synchronized disk...

    def _remove_last_record_from_media(self):
        pass  # there, save to DB or to synchronized disk...

    def _commit_transaction_to_media(self):
        pass  # there, save to DB or to synchronized disk...


class TransactionBase(object):

    def __init__(self, action_registry, action_recorder=None):

        self._action_registry = action_registry

        if not action_recorder:
            action_recorder = ActionRecorderBase()
        self._action_recorder = action_recorder

    def __getattr__(self, name):
        if not name in self._action_registry.list_registered_actions():
            raise AttributeError("Action Registry of %r has no action called %s" % (self, name))
        return functools.partial(self.tx_process_action, name)

    def _execute_selected_action(self, name, args=[], kwargs={}):

        action = self._action_registry.get_action(name)  # might raise exceptions - no rollback needed in this case
        # might raise exceptions - no rollback needed in this case
        (new_args, new_kwargs) = action.preprocess_arguments(*args, **kwargs)

        with recording_failure_handler():
            self._begin_action_processing(name, new_args, new_kwargs)

        result = action.process_action(*new_args, **new_kwargs)  # might raise exceptions - recovery needed then

        with recording_failure_handler():
            self._finish_action_processing(result)

        return result

    def _rollback_to_last_consistent_state(self):
        """

        May raise TransactionRecordingFailure errors, or any exception raised by the rollback operation.
        """

        with recording_failure_handler():
            need_unfinished_action_rollback = not self._action_recorder.is_empty() and not self._action_recorder.last_action_is_finished()

        if need_unfinished_action_rollback:

            with recording_failure_handler():
                (name, args, kwargs) = self._action_recorder.get_unfinished_action()
                action = self._action_registry.get_action(name)

            # we try to rollback the unfinished action
            action.rollback_action(args=args, kwargs=kwargs, was_interrupted=True)

            with recording_failure_handler():
                self._action_recorder.rollback_unfinished_action()

            return True

        return False

    def _rollback_consistent_transaction(self, rollback_to_last_savepoint=False):
        """
        Warning : if rollback_to_last_savepoint is True, the last savepoint itself is NOT removed !
        """
        if not (self._action_recorder.is_empty() or self._action_recorder.last_action_is_finished()):
            raise TransactionWorkflowError("Error issuing a consistent rollback on an inconsistent transaction")

        if rollback_to_last_savepoint:
            actions_to_undo = self._action_recorder.get_action_count_since_last_savepoint()
        else:
            if self._action_recorder.get_savepoint_count():
                raise TransactionWorkflowError("Remaining savepoints block the full rollback")
            actions_to_undo = self._action_recorder.get_action_count()

        for _ in range(actions_to_undo):

            with recording_failure_handler():
                ((name, args, kwargs), result) = self._action_recorder.get_finished_action()
                action = self._action_registry.get_action(name)

            action.rollback_action(args=args, kwargs=kwargs, was_interrupted=False,
                                   result=result)  # we try to rollback the last finished action

            with recording_failure_handler():
                self._action_recorder.rollback_finished_action()

        assert rollback_to_last_savepoint or self._action_recorder.is_empty(), "incoherence in _rollback_consistent_transaction"

    def _commit_consistent_transaction(self):

        if not (self._action_recorder.is_empty() or self._action_recorder.last_action_is_finished()):
            raise TransactionWorkflowError("Error issuing a consistent commit on an inconsistent transaction")

        with recording_failure_handler():
            self._action_recorder.commit_transaction()

    def _begin_action_processing(self, name, args, kwargs):
        record = (name, args, kwargs)
        self._action_recorder.begin_action_processing(record)

    def _finish_action_processing(self, result):
        self._action_recorder.finish_action_processing(result)

    # To be overridden in subclasses !!!

    def tx_process_action(self, name, *args, **kwargs):
        raise NotImplementedError(__name__)

    def tx_rollback(self):
        raise NotImplementedError(__name__)

    def tx_commit(self):
        raise NotImplementedError(__name__)

    def tx_create_savepoint(self):
        raise NotImplementedError(__name__)

    def tx_rollback_savepoint(self):
        raise NotImplementedError(__name__)

    def tx_commit_savepoint(self):
        raise NotImplementedError(__name__)


class InteractiveTransaction(TransactionBase):
    
    def __init__(self, action_registry, action_recorder=None):
        super(InteractiveTransaction, self).__init__(action_registry=action_registry, action_recorder=action_recorder)
        self._is_in_context_manager_transaction = False
        
    def tx_process_action(self, name, *args, **kwargs):

        if not (self._action_recorder.is_empty() or self._action_recorder.last_action_is_finished()
                ):  # no unfinished action must be pending
            raise TransactionWorkflowError("Can't process new action while another one is in process")

        try:
            return self._execute_selected_action(name, args, kwargs)
        except TransactionFailure:
            raise  # that's very bad... just let it propagate
        except Exception as e:
            raise e  # we just reraise the original exception

    def tx_rollback(self):
        try:
            self._rollback_to_last_consistent_state()  # in case it's not done yet
            self._rollback_consistent_transaction()
        except Exception as f:
            # TODO - PY3K - real exception chaining required here !
            raise TransactionRollbackFailure("%r raised during rollback attempt" % f)

    def tx_commit(self):
        self._commit_consistent_transaction()  # should already raise proper exceptions
        
        
    def __enter__(self):
        if self._is_in_context_manager_transaction or self._action_recorder.get_action_count():
            raise TransactionWorkflowError("Can't start a new transaction while another is still in process")
        self._is_in_context_manager_transaction = True
        
    def __exit__(self, eType, eValue, eTrace):
        self._is_in_context_manager_transaction = False
        if eType:
            self.tx_rollback()
        else: 
            self.tx_commit()
        
    
    @contextmanager
    def tx_savepoint(self):
        self.tx_create_savepoint()
        try:
            yield
        except TransactionFailure:
            raise  # we must not try to handle this critical problem by ourselves...
        except Exception:
            self.tx_rollback_savepoint()
            raise
        else:
            self.tx_commit_savepoint()

    def tx_create_savepoint(self):
        self._action_recorder.create_savepoint()

    def tx_rollback_savepoint(self):
        self._rollback_consistent_transaction(rollback_to_last_savepoint=True)
        self._action_recorder.rollback_last_savepoint()

    def tx_commit_savepoint(self):
        self._action_recorder.commit_last_savepoint()
