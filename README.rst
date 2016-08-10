RSTRANSACTION
================

Rstransaction is a python2/python3 toolbox to create transactional systems, for any kind of operations: in-memory, on filesystems, on remote storages...

It supports commits/rollbacks and savepoints.

It was never used in production, but is well tested, and easily extendable to support different kinds of behaviour : immediate or lazy actions, recording of operations to disk files or DBs in case of crash, auto-rollback on error or not...


INSTALL
------------

Using pip is recommended, although installing from a checkout of the repository (via setup.py) also works:

::

    $ pip install rstransaction


USAGE
---------

Your best bet is to read the sources (especially tests).

The idea is to create "atomic" operations using `TransactionalActionAdapter`.
Each of these operations knows how to operate, how to rollback itself, and also 
how to preprocess its arguments so that they are unambiguous (ex. turn 
relative file names into absolute ones).

These actions are then registered near a `TransactionalActionRegistry`.

An action recorder has to be chosen (the default one, `ActionRecorderBase`, 
simply records actions in-memory, without persistence).

A transaction processor (inheriting `TransactionBase`) is then instantiated, and 
given the action registry as well as the action recorder.
The default transaction processor, `InteractiveTransaction`, executes any operation 
(issued with tx_process_action()), immediately, so potential errors must be handled
accordingly. But one could implement a transaction processor which delays all operations 
until commit time.

Transaction steps can be set manually (with tx_commit(), tx_rollback(), savepoint methods..), but the best is to use
the transaction processor as a context manager (`with` keyword), so that full commit/rollback occur automatically on exit.
The "tx_savepoint" attribute of transaction processor can also be used as a context manager, only acting on a savepoint this time.

A transaction processor automatically begins a new transaction, on commit or rollback, so it can be reused.

Note that exceptions do not get swallowed by this system, even if an automatic rollback occurs.

Subclasses of `TransactionFailure` are used to report errors linked to the transaction systemn, as exceptions.

