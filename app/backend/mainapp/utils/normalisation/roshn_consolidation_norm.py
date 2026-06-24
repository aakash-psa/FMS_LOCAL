import numpy as np
import pandas as pd
import traceback
from datetime import datetime, date
from calendar import month
from contextlib import contextmanager
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from math import perm
from dateutil.relativedelta import relativedelta
import os
import re
import time

def wrapper_for_vars(payload, is_save):
    try:

            final_output = {
                "payload": payload,
                "is_save": is_save
            }
            
            return {
                "excel_output": {
                    "monthly_dfs": {},  # Placeholder for monthly DataFrames
                    "annual_dfs": {}    # Placeholder for annual DataFrames
                },
                "final_output": final_output
            }

    except Exception as e:
        print(f"Failed to initialise values {e}\n{traceback.format_exc()}")
        return {"error": str(e), "excel_output": {"monthly_dfs": {}, "annual_dfs": {}}}


def fninitialising_all_values(payload,is_save):
    try:
        output = wrapper_for_vars(payload, is_save)
        if output is None:
            return {"error": "Model returned None", "excel_output": {"monthly_dfs": {}, "annual_dfs": {}}}
        return output
    except Exception as e:
        print(f"Error in initialising all values: {e}")
        return {"error": str(e), "excel_output": {"monthly_dfs": {}, "annual_dfs": {}}}
