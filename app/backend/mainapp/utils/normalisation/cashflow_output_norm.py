import json
import numpy as np
# import polars as pl
import time
import timeit

def extract_period_end(timeline_obj):
    """Extract Period End dates from timeline object (vectorized)."""
    timeline_data = timeline_obj[1]
    period_end_pos = timeline_data['index'].index('Period End')
    return np.array(timeline_data['data'][period_end_pos], dtype='object')


def calculate_total_rows(data):
    """Pre-calculate total rows needed to allocate arrays upfront."""
    total = 0
    for entity_name, entity_data in data.items():
        # Find timeline in this entity
        timeline_obj = None
        for cat_name, cat_obj in entity_data.items():
            if 'Timeline' in cat_name and isinstance(cat_obj, list):
                timeline_obj = cat_obj
                break
        
        if timeline_obj is None:
            continue
        
        period_count = len(extract_period_end(timeline_obj))
        
        for cat_name, cat_obj in entity_data.items():
            if 'Timeline' in cat_name or not isinstance(cat_obj, list):
                continue
            
            cat_data = cat_obj[1]
            fact_count = len(cat_data['index'])
            total += fact_count * period_count
    
    return total

def normalize_data_v2(data):
    total_rows = calculate_total_rows(data)
    final_array = np.empty((total_rows, 4), dtype=object)
    row_idx = 0

    for entity_name, entity_data in data.items():
        # Find timeline for this entity
        period_items_ = None
        for category, category_data in entity_data.items():
            if "timeline" in category.lower() and isinstance(category_data, list):
                period_items_ = extract_period_end(category_data)
                break
        
        if period_items_ is None:
            continue
        
        # Process all non-timeline categories
        for category, category_data in entity_data.items():
            if "timeline" in category.lower() or not isinstance(category_data, list):
                continue
            
            data_items = np.array(category_data[1]['index'])
            row_count = data_items.shape[0]
            column_count = period_items_.shape[0]
            
            data_items = np.repeat(data_items, column_count)
            period_items = np.tile(period_items_, row_count)
            
            data_object = np.array(category_data[1]['data'])
            data_object_unpivoted = data_object.reshape(-1, 1)
            n_rows = data_object_unpivoted.shape[0]
            
            category_array = np.full(n_rows, category)
            
            # Assign to pre-allocated array (no vstack!)
            final_array[row_idx:row_idx + n_rows] = np.column_stack(
                [category_array, data_items, period_items, data_object_unpivoted]
            )
            row_idx += n_rows
    
    values_column = final_array[:, 3]

    # Replace empty strings and None with NaN for numeric conversion
    values_column_clean = np.where(
        (values_column == '') | (values_column == None), 
        np.nan, 
        values_column
    )
    
    # Convert to float for comparison
    try:
        values_column_float = values_column_clean.astype(float)
    except (ValueError, TypeError):
        # If conversion still fails, replace non-numeric values with NaN
        values_column_float = np.array([
            float(v) if isinstance(v, (int, float)) or (isinstance(v, str) and v.replace('.', '', 1).replace('-', '', 1).isdigit()) 
            else np.nan 
            for v in values_column_clean
        ])

    # Create mask for non-zero AND non-null values
    mask = (values_column_float != 0) & ~np.isnan(values_column_float)

    # Filter array to keep only valid rows
    filtered_array = final_array[mask]

    # Convert NumPy array to list for JSON serialization
    return filtered_array.tolist()