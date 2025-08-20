import os
import re
import yaml
from pocketflow import Node, BatchNode
from utils.crawl_github_files import crawl_github_files
from utils.call_llm import call_llm
from utils.crawl_local_files import crawl_local_files


# Helper to get content for specific file indices
def get_content_for_indices(files_data, indices):
    content_map = {}
    for i in indices:
        if 0 <= i < len(files_data):
            path, content = files_data[i]
            content_map[f"{i} # {path}"] = (
                content  # Use index + path as key for context
            )
    return content_map


class FetchRepo(Node):
    def prep(self, shared):
        repo_url = shared.get("repo_url")
        local_dir = shared.get("local_dir")
        project_name = shared.get("project_name")

        if not project_name:
            # Basic name derivation from URL or directory
            if repo_url:
                project_name = repo_url.split("/")[-1].replace(".git", "")
            else:
                project_name = os.path.basename(os.path.abspath(local_dir))
            shared["project_name"] = project_name

        # Get file patterns directly from shared
        include_patterns = shared["include_patterns"]
        exclude_patterns = shared["exclude_patterns"]
        max_file_size = shared["max_file_size"]

        return {
            "repo_url": repo_url,
            "local_dir": local_dir,
            "token": shared.get("github_token"),
            "include_patterns": include_patterns,
            "exclude_patterns": exclude_patterns,
            "max_file_size": max_file_size,
            "use_relative_paths": True,
        }

    def exec(self, prep_res):
        if prep_res["repo_url"]:
            print(f"Crawling repository: {prep_res['repo_url']}...")
            result = crawl_github_files(
                repo_url=prep_res["repo_url"],
                token=prep_res["token"],
                include_patterns=prep_res["include_patterns"],
                exclude_patterns=prep_res["exclude_patterns"],
                max_file_size=prep_res["max_file_size"],
                use_relative_paths=prep_res["use_relative_paths"],
            )
        else:
            print(f"Crawling directory: {prep_res['local_dir']}...")

            result = crawl_local_files(
                directory=prep_res["local_dir"],
                include_patterns=prep_res["include_patterns"],
                exclude_patterns=prep_res["exclude_patterns"],
                max_file_size=prep_res["max_file_size"],
                use_relative_paths=prep_res["use_relative_paths"]
            )

        # Convert dict to list of tuples: [(path, content), ...]
        files_list = list(result.get("files", {}).items())
        if len(files_list) == 0:
            raise (ValueError("Failed to fetch files"))
        print(f"Fetched {len(files_list)} files.")
        return files_list

    def post(self, shared, prep_res, exec_res):
        shared["files"] = exec_res  # List of (path, content) tuples


class IdentifyTables(Node):
    def prep(self, shared):
        files_data = shared["files"]
        project_name = shared["project_name"]  # Get project name
        language = shared.get("language", "english")  # Get language
        use_cache = shared.get("use_cache", True)  # Get use_cache flag, default to True
        max_table_num = shared.get("max_abstraction_num", 15)  # Renamed to max_table_num, increased default

        # Helper to create context from files, respecting limits (basic example)
        def create_llm_context(files_data):
            context = ""
            file_info = []  # Store tuples of (index, path)
            for i, (path, content) in enumerate(files_data):
                entry = f"--- File Index {i}: {path} ---\n{content}\n\n"
                context += entry
                file_info.append((i, path))

            return context, file_info  # file_info is list of (index, path)

        context, file_info = create_llm_context(files_data)
        # Format file info for the prompt (comment is just a hint for LLM)
        file_listing_for_prompt = "\n".join(
            [f"- {idx} # {path}" for idx, path in file_info]
        )
        return (
            context,
            file_listing_for_prompt,
            len(files_data),
            project_name,
            language,
            use_cache,
            max_table_num,
        )  # Return all parameters

    def exec(self, prep_res):
        (
            context,
            file_listing_for_prompt,
            file_count,
            project_name,
            language,
            use_cache,
            max_table_num,
        ) = prep_res  # Unpack all parameters
        print(f"Identifying database tables/models using LLM...")

        # Add language instruction and hints only if not English
        language_instruction = ""
        name_lang_hint = ""
        desc_lang_hint = ""
        if language.lower() != "english":
            language_instruction = f"IMPORTANT: Generate the `name` and `description` for each table in **{language.capitalize()}** language. Do NOT use English for these fields.\n\n"
            # Keep specific hints here as name/description are primary targets
            name_lang_hint = f" (value in {language.capitalize()})"
            desc_lang_hint = f" (value in {language.capitalize()})"

        prompt = f"""
For the project `{project_name}`:

Codebase Context:
{context}

{language_instruction}Analyze the codebase context to identify database tables, models, or data structures used for data persistence.
Look for:
- Database table definitions (SQL CREATE TABLE statements)
- ORM model classes (like SQLAlchemy, Django models, Hibernate entities)
- Data transfer objects or entities that represent database tables
- Schema definitions in migration files
- Database configuration files

Identify the top 5-{max_table_num} most important database tables/models.

For each table/model, provide:
1. A concise `name`{name_lang_hint} (the actual table/model name).
2. A beginner-friendly `description` explaining what data this table stores, in around 100 words{desc_lang_hint}.
3. A list of relevant `file_indices` (integers) where this table/model is defined or used.

List of file indices and paths present in the context:
{file_listing_for_prompt}

Format the output as a YAML list of dictionaries:

```yaml
- name: |
    users{name_lang_hint}
  description: |
    Stores user account information including authentication details,
    profile data, and user preferences. This is the main table for 
    managing user accounts in the system.{desc_lang_hint}
  file_indices:
    - 0 # path/to/user_model.py
    - 3 # path/to/migrations/create_users.sql
- name: |
    orders{name_lang_hint}
  description: |
    Contains customer order information including order details,
    status, and payment information.{desc_lang_hint}
  file_indices:
    - 5 # path/to/order_model.py
# ... up to {max_table_num} tables
```"""
        response = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0))  # Use cache only if enabled and not retrying

        # --- Validation ---
        yaml_str = response.strip().split("```yaml")[1].split("```")[0].strip()
        tables = yaml.safe_load(yaml_str)

        if not isinstance(tables, list):
            raise ValueError("LLM Output is not a list")

        validated_tables = []
        for item in tables:
            if not isinstance(item, dict) or not all(
                k in item for k in ["name", "description", "file_indices"]
            ):
                raise ValueError(f"Missing keys in table item: {item}")
            if not isinstance(item["name"], str):
                raise ValueError(f"Name is not a string in item: {item}")
            if not isinstance(item["description"], str):
                raise ValueError(f"Description is not a string in item: {item}")
            if not isinstance(item["file_indices"], list):
                raise ValueError(f"file_indices is not a list in item: {item}")

            # Validate indices
            validated_indices = []
            for idx_entry in item["file_indices"]:
                try:
                    if isinstance(idx_entry, int):
                        idx = idx_entry
                    elif isinstance(idx_entry, str) and "#" in idx_entry:
                        idx = int(idx_entry.split("#")[0].strip())
                    else:
                        idx = int(str(idx_entry).strip())

                    if not (0 <= idx < file_count):
                        raise ValueError(
                            f"Invalid file index {idx} found in item {item['name']}. Max index is {file_count - 1}."
                        )
                    validated_indices.append(idx)
                except (ValueError, TypeError):
                    raise ValueError(
                        f"Could not parse index from entry: {idx_entry} in item {item['name']}"
                    )

            item["files"] = sorted(list(set(validated_indices)))
            # Store only the required fields
            validated_tables.append(
                {
                    "name": item["name"],  # Potentially translated name
                    "description": item[
                        "description"
                    ],  # Potentially translated description
                    "files": item["files"],
                }
            )

        print(f"Identified {len(validated_tables)} database tables/models.")
        return validated_tables

    def post(self, shared, prep_res, exec_res):
        shared["tables"] = (
            exec_res  # List of {"name": str, "description": str, "files": [int]}
        )


class AnalyzeTableRelationships(Node):
    def prep(self, shared):
        tables = shared[
            "tables"
        ]  # Now contains 'files' list of indices, name/description potentially translated
        files_data = shared["files"]
        project_name = shared["project_name"]  # Get project name
        language = shared.get("language", "english")  # Get language
        use_cache = shared.get("use_cache", True)  # Get use_cache flag, default to True

        # Get the actual number of tables directly
        num_tables = len(tables)

        # Create context with table names, indices, descriptions, and relevant file snippets
        context = "Identified Database Tables:\\n"
        all_relevant_indices = set()
        table_info_for_prompt = []
        for i, table in enumerate(tables):
            # Use 'files' which contains indices directly
            file_indices_str = ", ".join(map(str, table["files"]))
            # Table name and description might be translated already
            info_line = f"- Index {i}: {table['name']} (Relevant file indices: [{file_indices_str}])\\n  Description: {table['description']}"
            context += info_line + "\\n"
            table_info_for_prompt.append(
                f"{i} # {table['name']}"
            )  # Use potentially translated name here too
            all_relevant_indices.update(table["files"])

        context += "\\nRelevant File Snippets (Referenced by Index and Path):\\n"
        # Get content for relevant files using helper
        relevant_files_content_map = get_content_for_indices(
            files_data, sorted(list(all_relevant_indices))
        )
        # Format file content for context
        file_context_str = "\\n\\n".join(
            f"--- File: {idx_path} ---\\n{content}"
            for idx_path, content in relevant_files_content_map.items()
        )
        context += file_context_str

        return (
            context,
            "\n".join(table_info_for_prompt),
            num_tables, # Pass the actual count
            project_name,
            language,
            use_cache,
        )  # Return use_cache

    def exec(self, prep_res):
        (
            context,
            table_listing,
            num_tables, # Receive the actual count
            project_name,
            language,
            use_cache,
         ) = prep_res  # Unpack use_cache
        print(f"Analyzing database table relationships using LLM...")

        # Add language instruction and hints only if not English
        language_instruction = ""
        lang_hint = ""
        list_lang_note = ""
        if language.lower() != "english":
            language_instruction = f"IMPORTANT: Generate the `summary` and relationship `label` fields in **{language.capitalize()}** language. Do NOT use English for these fields.\n\n"
            lang_hint = f" (in {language.capitalize()})"
            list_lang_note = f" (Names might be in {language.capitalize()})"  # Note for the input list

        prompt = f"""
Based on the following database tables and relevant code snippets from the project `{project_name}`:

List of Table Indices and Names{list_lang_note}:
{table_listing}

Context (Tables, Descriptions, Code):
{context}

{language_instruction}Please provide:
1. A high-level `summary` of the database schema's main purpose and the type of data it manages in a few beginner-friendly sentences{lang_hint}. Use markdown formatting with **bold** and *italic* text to highlight important concepts.
2. A list (`relationships`) describing the key relationships between these database tables. For each relationship, specify:
    - `from_table`: Index of the source table (e.g., `0 # TableName1`)
    - `to_table`: Index of the target table (e.g., `1 # TableName2`)
    - `label`: A brief label for the relationship **in just a few words**{lang_hint} (e.g., "Foreign Key", "One-to-Many", "References", "Belongs To").
    Look for:
    - Foreign key constraints
    - JOIN operations in queries
    - References between models/entities
    - Parent-child relationships
    - Association tables/junction tables

IMPORTANT: Make sure EVERY table is involved in at least ONE relationship (either as source or target). Each table index must appear at least once across all relationships.

Format the output as YAML:

```yaml
summary: |
  A brief, simple explanation of the database schema{lang_hint}.
  Can span multiple lines with **bold** and *italic* for emphasis.
relationships:
  - from_table: 0 # TableName1
    to_table: 1 # TableName2
    label: "Foreign Key"{lang_hint}
  - from_table: 2 # TableName3
    to_table: 0 # TableName1
    label: "References"{lang_hint}
  # ... other relationships
```

Now, provide the YAML output:
"""
        response = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0)) # Use cache only if enabled and not retrying

        # --- Validation ---
        yaml_str = response.strip().split("```yaml")[1].split("```")[0].strip()
        relationships_data = yaml.safe_load(yaml_str)

        if not isinstance(relationships_data, dict) or not all(
            k in relationships_data for k in ["summary", "relationships"]
        ):
            raise ValueError(
                "LLM output is not a dict or missing keys ('summary', 'relationships')"
            )
        if not isinstance(relationships_data["summary"], str):
            raise ValueError("summary is not a string")
        if not isinstance(relationships_data["relationships"], list):
            raise ValueError("relationships is not a list")

        # Validate relationships structure
        validated_relationships = []
        for rel in relationships_data["relationships"]:
            # Check for 'label' key
            if not isinstance(rel, dict) or not all(
                k in rel for k in ["from_table", "to_table", "label"]
            ):
                raise ValueError(
                    f"Missing keys (expected from_table, to_table, label) in relationship item: {rel}"
                )
            # Validate 'label' is a string
            if not isinstance(rel["label"], str):
                raise ValueError(f"Relationship label is not a string: {rel}")

            # Validate indices
            try:
                from_idx = int(str(rel["from_table"]).split("#")[0].strip())
                to_idx = int(str(rel["to_table"]).split("#")[0].strip())
                if not (
                    0 <= from_idx < num_tables and 0 <= to_idx < num_tables
                ):
                    raise ValueError(
                        f"Invalid index in relationship: from={from_idx}, to={to_idx}. Max index is {num_tables-1}."
                    )
                validated_relationships.append(
                    {
                        "from": from_idx,
                        "to": to_idx,
                        "label": rel["label"],  # Potentially translated label
                    }
                )
            except (ValueError, TypeError):
                raise ValueError(f"Could not parse indices from relationship: {rel}")

        print("Generated database schema summary and relationship details.")
        return {
            "summary": relationships_data["summary"],  # Potentially translated summary
            "details": validated_relationships,  # Store validated, index-based relationships with potentially translated labels
        }

    def post(self, shared, prep_res, exec_res):
        # Structure is now {"summary": str, "details": [{"from": int, "to": int, "label": str}]}
        # Summary and label might be translated
        shared["relationships"] = exec_res


class OrderTables(Node):
    def prep(self, shared):
        tables = shared["tables"]  # Name/description might be translated
        relationships = shared["relationships"]  # Summary/label might be translated
        project_name = shared["project_name"]  # Get project name
        language = shared.get("language", "english")  # Get language
        use_cache = shared.get("use_cache", True)  # Get use_cache flag, default to True

        # Prepare context for the LLM
        table_info_for_prompt = []
        for i, t in enumerate(tables):
            table_info_for_prompt.append(
                f"- {i} # {t['name']}"
            )  # Use potentially translated name
        table_listing = "\n".join(table_info_for_prompt)

        # Use potentially translated summary and labels
        summary_note = ""
        if language.lower() != "english":
            summary_note = (
                f" (Note: Schema Summary might be in {language.capitalize()})"
            )

        context = f"Database Schema Summary{summary_note}:\n{relationships['summary']}\n\n"
        context += "Table Relationships (Indices refer to tables above):\n"
        for rel in relationships["details"]:
            from_name = tables[rel["from"]]["name"]
            to_name = tables[rel["to"]]["name"]
            # Use potentially translated 'label'
            context += f"- From {rel['from']} ({from_name}) to {rel['to']} ({to_name}): {rel['label']}\n"  # Label might be translated

        list_lang_note = ""
        if language.lower() != "english":
            list_lang_note = f" (Names might be in {language.capitalize()})"

        return (
            table_listing,
            context,
            len(tables),
            project_name,
            list_lang_note,
            use_cache,
        )  # Return use_cache

    def exec(self, prep_res):
        (
            table_listing,
            context,
            num_tables,
            project_name,
            list_lang_note,
            use_cache,
        ) = prep_res  # Unpack use_cache
        print("Determining table order using LLM...")
        # No language variation needed here in prompt instructions, just ordering based on structure
        # The input names might be translated, hence the note.
        prompt = f"""
Given the following database tables and their relationships for the project ```` {project_name} ````:

Database Tables (Index # Name){list_lang_note}:
{table_listing}

Context about relationships and schema summary:
{context}

If you are going to document the database schema for ```` {project_name} ````, what is the best order to present these tables, from first to last?
Ideally, first present the core/foundational tables (like users, accounts, basic entities), then move to tables that depend on them (like orders, transactions), and finally supporting/lookup tables (like settings, logs).

Consider:
- Primary entities first (users, accounts, products)
- Tables with foreign keys should come after the tables they reference
- Dependent/child tables should come after parent tables
- Supporting/lookup tables typically come last

Output the ordered list of table indices, including the name in a comment for clarity. Use the format `idx # TableName`.

```yaml
- 2 # users
- 0 # products  
- 1 # orders (references users and products)
- ...
```

Now, provide the YAML output:
"""
        response = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0)) # Use cache only if enabled and not retrying

        # --- Validation ---
        yaml_str = response.strip().split("```yaml")[1].split("```")[0].strip()
        ordered_indices_raw = yaml.safe_load(yaml_str)

        if not isinstance(ordered_indices_raw, list):
            raise ValueError("LLM output is not a list")

        ordered_indices = []
        seen_indices = set()
        for entry in ordered_indices_raw:
            try:
                if isinstance(entry, int):
                    idx = entry
                elif isinstance(entry, str) and "#" in entry:
                    idx = int(entry.split("#")[0].strip())
                else:
                    idx = int(str(entry).strip())

                if not (0 <= idx < num_tables):
                    raise ValueError(
                        f"Invalid index {idx} in ordered list. Max index is {num_tables-1}."
                    )
                if idx in seen_indices:
                    raise ValueError(f"Duplicate index {idx} found in ordered list.")
                ordered_indices.append(idx)
                seen_indices.add(idx)

            except (ValueError, TypeError):
                raise ValueError(
                    f"Could not parse index from ordered list entry: {entry}"
                )

        # Check if all tables are included
        if len(ordered_indices) != num_tables:
            raise ValueError(
                f"Ordered list length ({len(ordered_indices)}) does not match number of tables ({num_tables}). Missing indices: {set(range(num_tables)) - seen_indices}"
            )

        print(f"Determined table order (indices): {ordered_indices}")
        return ordered_indices  # Return the list of indices

    def post(self, shared, prep_res, exec_res):
        # exec_res is already the list of ordered indices
        shared["table_order"] = exec_res  # List of indices


class WriteTableSchemas(BatchNode):
    def prep(self, shared):
        table_order = shared["table_order"]  # List of indices
        tables = shared[
            "tables"
        ]  # List of {"name": str, "description": str, "files": [int]}
        files_data = shared["files"]  # List of (path, content) tuples
        project_name = shared["project_name"]
        language = shared.get("language", "english")
        use_cache = shared.get("use_cache", True)  # Get use_cache flag, default to True

        # Get already written table schemas to provide context
        # We store them temporarily during the batch run, not in shared memory yet
        # The 'previous_schemas_summary' will be built progressively in the exec context
        self.schemas_written_so_far = (
            []
        )  # Use instance variable for temporary storage across exec calls

        # Create a complete list of all table schemas
        all_table_schemas = []
        table_filenames = {}  # Store table filename mapping for linking
        for i, table_index in enumerate(table_order):
            if 0 <= table_index < len(tables):
                schema_num = i + 1
                table_name = tables[table_index][
                    "name"
                ]  # Potentially translated name
                # Create safe filename (from potentially translated name)
                safe_name = "".join(
                    c if c.isalnum() else "_" for c in table_name
                ).lower()
                filename = f"{i+1:02d}_{safe_name}.md"
                # Format with link (using potentially translated name)
                all_table_schemas.append(f"{schema_num}. [{table_name}]({filename})")
                # Store mapping of table index to filename for linking
                table_filenames[table_index] = {
                    "num": schema_num,
                    "name": table_name,
                    "filename": filename,
                }

        # Create a formatted string with all table schemas
        full_schema_listing = "\n".join(all_table_schemas)

        items_to_process = []
        for i, table_index in enumerate(table_order):
            if 0 <= table_index < len(tables):
                table_details = tables[
                    table_index
                ]  # Contains potentially translated name/desc
                # Use 'files' (list of indices) directly
                related_file_indices = table_details.get("files", [])
                # Get content using helper, passing indices
                related_files_content_map = get_content_for_indices(
                    files_data, related_file_indices
                )

                # Get previous table info for references (uses potentially translated name)
                prev_table = None
                if i > 0:
                    prev_idx = table_order[i - 1]
                    prev_table = table_filenames[prev_idx]

                # Get next table info for references (uses potentially translated name)
                next_table = None
                if i < len(table_order) - 1:
                    next_idx = table_order[i + 1]
                    next_table = table_filenames[next_idx]

                items_to_process.append(
                    {
                        "schema_num": i + 1,
                        "table_index": table_index,
                        "table_details": table_details,  # Has potentially translated name/desc
                        "related_files_content_map": related_files_content_map,
                        "project_name": shared["project_name"],  # Add project name
                        "full_schema_listing": full_schema_listing,  # Add the full schema listing (uses potentially translated names)
                        "table_filenames": table_filenames,  # Add table filenames mapping (uses potentially translated names)
                        "prev_table": prev_table,  # Add previous table info (uses potentially translated name)
                        "next_table": next_table,  # Add next table info (uses potentially translated name)
                        "language": language,  # Add language for multi-language support
                        "use_cache": use_cache, # Pass use_cache flag
                        # previous_schemas_summary will be added dynamically in exec
                    }
                )
            else:
                print(
                    f"Warning: Invalid table index {table_index} in table_order. Skipping."
                )

        print(f"Preparing to write {len(items_to_process)} table schemas...")
        return items_to_process  # Iterable for BatchNode

    def exec(self, item):
        # This runs for each item prepared above
        table_name = item["table_details"][
            "name"
        ]  # Potentially translated name
        table_description = item["table_details"][
            "description"
        ]  # Potentially translated description
        schema_num = item["schema_num"]
        project_name = item.get("project_name")
        language = item.get("language", "english")
        use_cache = item.get("use_cache", True) # Read use_cache from item
        print(f"Writing schema documentation {schema_num} for table: {table_name} using LLM...")

        # Prepare file context string from the map
        file_context_str = "\n\n".join(
            f"--- File: {idx_path.split('# ')[1] if '# ' in idx_path else idx_path} ---\n{content}"
            for idx_path, content in item["related_files_content_map"].items()
        )

        # Get summary of schemas written *before* this one
        # Use the temporary instance variable
        previous_schemas_summary = "\n---\n".join(self.schemas_written_so_far)

        # Add language instruction and context notes only if not English
        language_instruction = ""
        table_details_note = ""
        structure_note = ""
        prev_summary_note = ""
        instruction_lang_note = ""
        link_lang_note = ""
        tone_note = ""
        if language.lower() != "english":
            lang_cap = language.capitalize()
            language_instruction = f"IMPORTANT: Write this ENTIRE table schema documentation in **{lang_cap}**. Some input context (like table name, description, schema list, previous summary) might already be in {lang_cap}, but you MUST translate ALL other generated content including explanations, column descriptions, constraint descriptions into {lang_cap}. DO NOT use English anywhere except in actual code/SQL syntax, required technical terms, or when specified. The entire output MUST be in {lang_cap}.\n\n"
            table_details_note = f" (Note: Provided in {lang_cap})"
            structure_note = f" (Note: Table names might be in {lang_cap})"
            prev_summary_note = f" (Note: This summary might be in {lang_cap})"
            instruction_lang_note = f" (in {lang_cap})"
            link_lang_note = (
                f" (Use the {lang_cap} table name from the structure above)"
            )
            tone_note = f" (appropriate for {lang_cap} readers)"

        prompt = f"""
{language_instruction}Write a comprehensive database table schema documentation (in Markdown format) for the project `{project_name}` about the table: "{table_name}". This is Table Schema {schema_num}.

Table Details{table_details_note}:
- Name: {table_name}
- Description:
{table_description}

Complete Database Schema Structure{structure_note}:
{item["full_schema_listing"]}

Context from previous table schemas{prev_summary_note}:
{previous_schemas_summary if previous_schemas_summary else "This is the first table schema."}

Relevant Code Snippets (SQL/Code syntax remains unchanged):
{file_context_str if file_context_str else "No specific code snippets provided for this table."}

Instructions for the schema documentation (Generate content in {language.capitalize()} unless specified otherwise):
- Start with a clear heading (e.g., `# Table Schema {schema_num}: {table_name}`). Use the provided table name.

- Begin with a high-level overview explaining what this table stores and its role in the database{instruction_lang_note}. 

- **Columns Section**: Create a detailed table with the following columns{instruction_lang_note}:
  - Column Name
  - Data Type
  - Constraints (NOT NULL, PRIMARY KEY, FOREIGN KEY, UNIQUE, etc.)
  - Description{instruction_lang_note}
  - Possible Values (especially for ENUMs, boolean fields, or fields with restricted values){instruction_lang_note}

- For ENUM fields or fields with restricted values, provide a detailed explanation of what each value represents{instruction_lang_note}.

- **Constraints and Indexes**: List all constraints, primary keys, foreign keys, unique constraints, and indexes{instruction_lang_note}.

- **Relationships**: Explain how this table relates to other tables in the database{instruction_lang_note}. If this table references other tables, use proper Markdown links like this: [Table Name](filename.md) using the Complete Database Schema Structure above{link_lang_note}.

- **Example Data**: Provide sample data showing what typical records might look like{instruction_lang_note}.

- **SQL Schema**: If possible from the code context, provide the actual CREATE TABLE statement or equivalent ORM model definition.

- Use clear formatting with tables and code blocks to make the schema easy to read{instruction_lang_note}.

- End with any additional notes about usage patterns, performance considerations, or data validation rules{instruction_lang_note}.

- Output *only* the Markdown content for this table schema documentation.

Now, directly provide a comprehensive Markdown output (DON'T need ```markdown``` tags):
"""
        schema_content = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0)) # Use cache only if enabled and not retrying
        # Basic validation/cleanup
        actual_heading = f"# Table Schema {schema_num}: {table_name}"  # Use potentially translated name
        if not schema_content.strip().startswith(f"# Table Schema {schema_num}"):
            # Add heading if missing or incorrect, trying to preserve content
            lines = schema_content.strip().split("\n")
            if lines and lines[0].strip().startswith(
                "#"
            ):  # If there's some heading, replace it
                lines[0] = actual_heading
                schema_content = "\n".join(lines)
            else:  # Otherwise, prepend it
                schema_content = f"{actual_heading}\n\n{schema_content}"

        # Add the generated content to our temporary list for the next iteration's context
        self.schemas_written_so_far.append(schema_content)

        return schema_content  # Return the Markdown string (potentially translated)

    def post(self, shared, prep_res, exec_res_list):
        # exec_res_list contains the generated Markdown for each table schema, in order
        shared["schemas"] = exec_res_list
        # Clean up the temporary instance variable
        del self.schemas_written_so_far
        print(f"Finished writing {len(exec_res_list)} table schemas.")


class CombineSchemas(Node):
    def prep(self, shared):
        project_name = shared["project_name"]
        output_base_dir = shared.get("output_dir", "output")  # Default output dir
        output_path = os.path.join(output_base_dir, project_name)
        repo_url = shared.get("repo_url")  # Get the repository URL
        # language = shared.get("language", "english") # No longer needed for fixed strings

        # Get potentially translated data
        relationships_data = shared[
            "relationships"
        ]  # {"summary": str, "details": [{"from": int, "to": int, "label": str}]} -> summary/label potentially translated
        table_order = shared["table_order"]  # indices
        tables = shared[
            "tables"
        ]  # list of dicts -> name/description potentially translated
        schemas_content = shared[
            "schemas"
        ]  # list of strings -> content potentially translated

        # --- Generate Mermaid Diagram ---
        mermaid_lines = ["erDiagram"]
        # Add table entities for each table using potentially translated names
        for i, table in enumerate(tables):
            table_id = f"T{i}"
            # Use potentially translated name, sanitize for Mermaid ID and label
            sanitized_name = table["name"].replace('"', '').replace(' ', '_')
            table_label = table["name"]  # Using original name for display
            mermaid_lines.append(
                f'    {sanitized_name} {{'
            )
            mermaid_lines.append(
                f'        string id PK'
            )
            mermaid_lines.append(
                f'    }}'
            )
        # Add relationships for foreign keys using potentially translated labels
        for rel in relationships_data["details"]:
            from_table = tables[rel['from']]["name"].replace('"', '').replace(' ', '_')
            to_table = tables[rel['to']]["name"].replace('"', '').replace(' ', '_')
            # Use potentially translated label, convert to ER notation
            relationship_type = "||--o|" if "one" in rel["label"].lower() else "||--||"
            mermaid_lines.append(
                f'    {from_table} {relationship_type} {to_table} : "{rel["label"]}"'
            )

        mermaid_diagram = "\n".join(mermaid_lines)
        # --- End Mermaid ---

        # --- Prepare index.md content ---
        index_content = f"# Database Schema: {project_name}\n\n"
        index_content += f"{relationships_data['summary']}\n\n"  # Use the potentially translated summary directly
        # Keep fixed strings in English
        index_content += f"**Source Repository:** [{repo_url}]({repo_url})\n\n"

        # Add Mermaid diagram for database relationships (diagram itself uses potentially translated names/labels)
        index_content += "## Database Schema Overview\n\n"
        index_content += "```mermaid\n"
        index_content += mermaid_diagram + "\n"
        index_content += "```\n\n"

        # Keep fixed strings in English
        index_content += f"## Table Schemas\n\n"

        schema_files = []
        # Generate table schema links based on the determined order, using potentially translated names
        for i, table_index in enumerate(table_order):
            # Ensure index is valid and we have content for it
            if 0 <= table_index < len(tables) and i < len(schemas_content):
                table_name = tables[table_index][
                    "name"
                ]  # Potentially translated name
                # Sanitize potentially translated name for filename
                safe_name = "".join(
                    c if c.isalnum() else "_" for c in table_name
                ).lower()
                filename = f"{i+1:02d}_{safe_name}.md"
                index_content += f"{i+1}. [{table_name}]({filename})\n"  # Use potentially translated name in link text

                # Add attribution to schema content (using English fixed string)
                schema_content = schemas_content[i]  # Potentially translated content
                if not schema_content.endswith("\n\n"):
                    schema_content += "\n\n"
                # Keep fixed strings in English
                schema_content += f"---\n\nGenerated by [AI Codebase Knowledge Builder](https://github.com/The-Pocket/Tutorial-Codebase-Knowledge)"

                # Store filename and corresponding content
                schema_files.append({"filename": filename, "content": schema_content})
            else:
                print(
                    f"Warning: Mismatch between table order, tables, or content at index {i} (table index {table_index}). Skipping file generation for this entry."
                )

        # Add attribution to index content (using English fixed string)
        index_content += f"\n\n---\n\nGenerated by [AI Codebase Knowledge Builder](https://github.com/The-Pocket/Tutorial-Codebase-Knowledge)"

        return {
            "output_path": output_path,
            "index_content": index_content,
            "schema_files": schema_files,  # List of {"filename": str, "content": str}
        }

    def exec(self, prep_res):
        output_path = prep_res["output_path"]
        index_content = prep_res["index_content"]
        schema_files = prep_res["schema_files"]

        print(f"Combining database schema documentation into directory: {output_path}")
        # Rely on Node's built-in retry/fallback
        os.makedirs(output_path, exist_ok=True)

        # Write index.md
        index_filepath = os.path.join(output_path, "index.md")
        with open(index_filepath, "w", encoding="utf-8") as f:
            f.write(index_content)
        print(f"  - Wrote {index_filepath}")

        # Write schema files
        for schema_info in schema_files:
            schema_filepath = os.path.join(output_path, schema_info["filename"])
            with open(schema_filepath, "w", encoding="utf-8") as f:
                f.write(schema_info["content"])
            print(f"  - Wrote {schema_filepath}")

        return output_path  # Return the final path

    def post(self, shared, prep_res, exec_res):
        shared["final_output_dir"] = exec_res  # Store the output path
        print(f"\nDatabase schema documentation generation complete! Files are in: {exec_res}")
