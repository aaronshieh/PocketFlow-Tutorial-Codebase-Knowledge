from pocketflow import Flow
# Import all node classes from nodes.py
from nodes import (
    FetchRepo,
    IdentifyTables,
    AnalyzeTableRelationships,
    OrderTables,
    WriteTableSchemas,
    CombineSchemas
)

def create_schema_flow():
    """Creates and returns the database schema generation flow."""

    # Instantiate nodes
    fetch_repo = FetchRepo()
    identify_tables = IdentifyTables(max_retries=5, wait=20)
    analyze_table_relationships = AnalyzeTableRelationships(max_retries=5, wait=20)
    order_tables = OrderTables(max_retries=5, wait=20)
    write_table_schemas = WriteTableSchemas(max_retries=5, wait=20) # This is a BatchNode
    combine_schemas = CombineSchemas()

    # Connect nodes in sequence based on the design
    fetch_repo >> identify_tables
    identify_tables >> analyze_table_relationships
    analyze_table_relationships >> order_tables
    order_tables >> write_table_schemas
    write_table_schemas >> combine_schemas

    # Create the flow starting with FetchRepo
    schema_flow = Flow(start=fetch_repo)

    return schema_flow

# Keep backward compatibility - alias the old function name
def create_tutorial_flow():
    """Backward compatibility wrapper - now creates schema flow instead."""
    return create_schema_flow()
