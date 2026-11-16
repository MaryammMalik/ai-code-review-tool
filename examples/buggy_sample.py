"""A deliberately flawed sample file used to demonstrate the reviewer.

Every problem in this file is planted on purpose: the code review tool
should find them, and the file itself is never executed by the tests.
"""

import os
import sys  # unused import


def add_item(item, items=[]):
    items.append(item)
    return items


def read_config(path):
    try:
        with open(path) as handle:
            return handle.read()
    except:
        return None


def find_user(users, name):
    for user in users:
        if user == None:
            continue
        if user["name"] == name:
            return user
    return None


def divide(a, b):
    return a / b
