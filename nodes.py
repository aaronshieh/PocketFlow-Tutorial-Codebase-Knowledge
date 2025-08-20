import os
import yaml
from pocketflow import Node, BatchNode
from utils.crawl_github_files import crawl_github_files
from utils.crawl_local_files import crawl_local_files
from utils.call_llm import call_llm


def get_content_for_indices(files_data, indices):
    content_map = {}
    for i in indices:
        if 0 <= i < len(files_data):
            path, content = files_data[i]
            content_map[f"{i} # {path}"] = content
    return content_map


class FetchRepo(Node):
    def prep(self, shared):
        repo_url = shared.get("repo_url")
        local_dir = shared.get("local_dir")
        project_name = shared.get("project_name")

        if not project_name:
            if repo_url:
                project_name = repo_url.split("/")[-1].replace(".git", "")
            else:
                project_name = os.path.basename(os.path.abspath(local_dir))
            shared["project_name"] = project_name

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
                use_relative_paths=prep_res["use_relative_paths"],
            )

        files_list = list(result.get("files", {}).items())
        if len(files_list) == 0:
            raise ValueError("Failed to fetch files")
        print(f"Fetched {len(files_list)} files.")
        return files_list

    def post(self, shared, prep_res, exec_res):
        shared["files"] = exec_res


class IdentifyTables(Node):
    def prep(self, shared):
        files_data = shared["files"]
        project_name = shared["project_name"]
        use_cache = shared.get("use_cache", True)

        context = ""
        file_info = []
        for i, (path, content) in enumerate(files_data):
            context += f"--- File Index {i}: {path} ---\n{content}\n\n"
            file_info.append((i, path))

        file_listing_for_prompt = "\n".join([f"- {idx} # {path}" for idx, path in file_info])
        return context, file_listing_for_prompt, len(files_data), project_name, use_cache

    def exec(self, prep_res):
        context, file_listing, file_count, project_name, use_cache = prep_res
        print("Identifying database tables using LLM...")
        prompt = f"""
For the project `{project_name}`:

Codebase Context:
{context}

Analyze the codebase to identify all database tables.
For each table provide:
1. `name` - the table name.
2. `description` - brief purpose of the table.
3. `file_indices` - list of file indices where the table is defined.

List of file indices and paths:
{file_listing}

Format the output as a YAML list of dictionaries:

```yaml
- name: users
  description: user accounts table
  file_indices:
    - 0 # path/to/models.py
    - 5 # path/to/schema.sql
# ...
```
"""
        response = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0))
        yaml_str = response.strip().split("```yaml")[1].split("```")[0].strip()
        tables = yaml.safe_load(yaml_str)

        if not isinstance(tables, list):
            raise ValueError("LLM Output is not a list")

        validated_tables = []
        for item in tables:
            if not isinstance(item, dict) or not all(k in item for k in ["name", "description", "file_indices"]):
                raise ValueError(f"Missing keys in table item: {item}")
            if not isinstance(item["name"], str):
                raise ValueError(f"Name is not a string in item: {item}")
            if not isinstance(item["description"], str):
                raise ValueError(f"Description is not a string in item: {item}")
            if not isinstance(item["file_indices"], list):
                raise ValueError(f"file_indices is not a list in item: {item}")

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
                            f"Invalid file index {idx} found in table {item['name']}. Max index is {file_count - 1}."
                        )
                    validated_indices.append(idx)
                except (ValueError, TypeError):
                    raise ValueError(f"Could not parse index from entry: {idx_entry} in table {item['name']}")
            validated_tables.append({
                "name": item["name"],
                "description": item["description"],
                "files": sorted(list(set(validated_indices)))
            })

        print(f"Identified {len(validated_tables)} tables.")
        return validated_tables

    def post(self, shared, prep_res, exec_res):
        shared["tables"] = exec_res


class DescribeTables(BatchNode):
    def prep(self, shared):
        tables = shared["tables"]
        files_data = shared["files"]
        project_name = shared["project_name"]
        use_cache = shared.get("use_cache", True)

        items = []
        for t in tables:
            content_map = get_content_for_indices(files_data, t["files"])
            file_context_str = "\n\n".join(
                f"--- File: {idx_path} ---\n{content}" for idx_path, content in content_map.items()
            )
            items.append((t["name"], t["description"], file_context_str, project_name, use_cache))
        return items

    def exec(self, prep_res):
        table_name, table_desc, file_context_str, project_name, use_cache = prep_res
        print(f"Describing columns for table {table_name} using LLM...")
        prompt = f"""
For the project `{project_name}`, analyze the following code snippets related to table `{table_name}`:

{file_context_str if file_context_str else 'No specific code snippets provided.'}

Provide the full database schema for table `{table_name}`. For each column include:
- `name`
- `type`
- `description`
- `values` (only if the column has a restricted set of values such as enums; map value to description)

Output the result in YAML:
```yaml
table: {table_name}
description: |
  {table_desc}
columns:
  - name: id
    type: integer
    description: unique identifier
  - name: status
    type: enum
    description: account status
    values:
      active: active user
      disabled: disabled user
```
"""
        response = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0))
        yaml_str = response.strip().split("```yaml")[1].split("```")[0].strip()
        table_schema = yaml.safe_load(yaml_str)

        if not isinstance(table_schema, dict) or not all(k in table_schema for k in ["table", "columns"]):
            raise ValueError("Invalid table schema returned by LLM")

        columns = table_schema["columns"]
        if not isinstance(columns, list):
            raise ValueError("`columns` should be a list")

        for col in columns:
            if not isinstance(col, dict) or not all(k in col for k in ["name", "type", "description"]):
                raise ValueError(f"Invalid column entry: {col}")
            if "values" in col and not isinstance(col["values"], dict):
                raise ValueError(f"values field must be a dict in column: {col}")

        return table_schema

    def post(self, shared, prep_res, exec_res_list):
        shared["schema"] = exec_res_list
        print(f"Generated schemas for {len(exec_res_list)} tables.")


class CombineSchema(Node):
    def prep(self, shared):
        project_name = shared["project_name"]
        output_base_dir = shared.get("output_dir", "output")
        output_path = os.path.join(output_base_dir, project_name, "schema.yaml")
        schema = shared["schema"]
        return output_path, schema

    def exec(self, prep_res):
        output_path, schema = prep_res
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump({"tables": schema}, f, sort_keys=False, allow_unicode=True)
        print(f"Wrote schema to {output_path}")
        return output_path

    def post(self, shared, prep_res, exec_res):
        shared["final_output_dir"] = os.path.dirname(exec_res)
