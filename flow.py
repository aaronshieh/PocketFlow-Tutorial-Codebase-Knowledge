from pocketflow import Flow
from nodes import (
    FetchRepo,
    IdentifyTables,
    DescribeTables,
    CombineSchema
)

def create_schema_flow():
    """Creates and returns the database schema generation flow."""

    fetch_repo = FetchRepo()
    identify_tables = IdentifyTables(max_retries=5, wait=20)
    describe_tables = DescribeTables(max_retries=5, wait=20)
    combine_schema = CombineSchema()

    fetch_repo >> identify_tables
    identify_tables >> describe_tables
    describe_tables >> combine_schema

    schema_flow = Flow(start=fetch_repo)
    return schema_flow
