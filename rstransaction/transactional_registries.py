#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
UNFINISHED action registry to make transactional filesystem operations (create files, move, delete them...)
"""

import sys, os, shutil, stat, random, time, tempfile
import unittest, collections

from . import transaction_processor as TP

# Temporary directory, very important to store intermediate data !!!
transaction_temp_dir = os.path.join(tempfile.gettempdir(), "FStransactions")
if not os.path.isdir(transaction_temp_dir):
    os.makedirs(transaction_temp_dir)
    

class ActionRenameFile(TP.TransactionalActionBase):
    
    def preprocess_arguments(self, src, dst, makedirs):

        new_src = os.path.realpath(src)
        new_dst = os.path.realpath(dst)
        
        src_copy = tempfile.mktemp(dir=transaction_temp_dir)
        if os.path:
            dst_copy = tempfile.mktemp(dir=transaction_temp_dir)
        else:
            dst_copy = None
            
        return (args, kwargs)
    
    @staticmethod
    def process_action(*args, **kwargs):
        pass # TODO
    
    @staticmethod
    def rollback_action(was_interrupted, args, kwargs, result=None):
        pass # TODO




