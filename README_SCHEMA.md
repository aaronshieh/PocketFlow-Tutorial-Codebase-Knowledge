# Database Schema Documentation Generator

> Transform any codebase into comprehensive database schema documentation with AI! This tool analyzes GitHub repositories and local directories to automatically identify database tables, extract detailed column information, and generate complete schema documentation.

This project has been transformed from the original [AI Codebase Knowledge Builder](https://github.com/The-Pocket/PocketFlow-Tutorial-Codebase-Knowledge) to focus specifically on **database schema extraction and documentation**. It uses AI to understand your codebase and produce detailed documentation for all database tables, including:

- **Complete table schemas** with column names, data types, and constraints
- **Detailed enum and value descriptions** for restricted fields
- **Foreign key relationships** and table dependencies
- **Interactive ER diagrams** showing table relationships
- **Sample data examples** and usage patterns
- **Multi-language support** for documentation

## 🚀 What This Tool Does

This tool analyzes codebases to find:
- Database table definitions (SQL CREATE TABLE statements)
- ORM model classes (SQLAlchemy, Django, Hibernate, etc.)
- Data transfer objects and entities
- Schema definitions in migration files
- Enum definitions and value constraints

Then generates comprehensive documentation including:
- **Table schemas** with complete column information
- **Relationship mappings** between tables
- **Constraint documentation** (primary keys, foreign keys, unique constraints)
- **Enum value explanations** - what each value represents
- **Interactive ER diagrams** using Mermaid
- **Example queries** and usage patterns

## 🎯 Perfect For

- **New team members** understanding database structure
- **API documentation** that needs schema details
- **Database migration planning**
- **Code reviews** requiring schema context
- **Technical documentation** for compliance
- **Legacy system analysis**

## 📊 Example Output

The tool generates a complete database schema documentation site with:

```
📁 output/your-project/
├── 📄 index.md              # Overview with ER diagram
├── 📄 01_users.md           # Users table schema
├── 📄 02_posts.md           # Posts table schema
└── 📄 03_comments.md        # Comments table schema
```

Each table document includes:
- **Column specifications** (name, type, constraints, descriptions)
- **Enum value definitions** (what each value means)
- **Foreign key relationships** with links to related tables
- **Sample data** showing typical records
- **SQL CREATE statements** or ORM model definitions

## 🚀 Getting Started

1. Clone this repository
   ```bash
   git clone https://github.com/aaronshieh/PocketFlow-Tutorial-Codebase-Knowledge
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set up LLM in [`utils/call_llm.py`](./utils/call_llm.py) by providing credentials. By default, you can use the [AI Studio key](https://aistudio.google.com/app/apikey) with this client for Gemini Pro 2.5:

   ```python
   client = genai.Client(
     api_key=os.getenv("GEMINI_API_KEY", "your-api_key"),
   )
   ```

   You can use your own models. We highly recommend the latest models with reasoning capabilities (Claude 3.7 with thinking, O1). You can verify that it is correctly set up by running:
   ```bash
   python utils/call_llm.py
   ```

4. Generate database schema documentation:
   ```bash
   # Analyze a GitHub repository
   python main.py --repo https://github.com/username/repo --include "*.py" "*.sql" --exclude "tests/*" --max-size 50000

   # Or, analyze a local directory
   python main.py --dir /path/to/your/codebase --include "*.py" "*.sql" --exclude "*test*"

   # Generate documentation in another language
   python main.py --repo https://github.com/username/repo --language "Spanish"
   ```

## 📋 Command Line Options

- `--repo` or `--dir` - Specify either a GitHub repo URL or a local directory path (required, mutually exclusive)
- `-n, --name` - Project name (optional, derived from URL/directory if omitted)
- `-t, --token` - GitHub token (or set GITHUB_TOKEN environment variable)
- `-o, --output` - Output directory (default: ./output)
- `-i, --include` - Files to include (e.g., "`*.py`" "`*.sql`" "`*.js`"). Defaults to common code and database files
- `-e, --exclude` - Files to exclude (e.g., "`tests/*`" "`docs/*`"). Defaults to test/build directories
- `-s, --max-size` - Maximum file size in bytes (default: 100KB)
- `--language` - Language for the generated documentation (default: "english")
- `--max-tables` - Maximum number of database tables to identify (default: 15)
- `--no-cache` - Disable LLM response caching (default: caching enabled)

## 🔍 Supported Database Technologies

The tool can identify and document tables from:

- **SQL databases**: PostgreSQL, MySQL, SQLite, SQL Server
- **ORM frameworks**: SQLAlchemy, Django ORM, Hibernate, TypeORM
- **Schema files**: `.sql`, `.ddl`, migration files
- **Programming languages**: Python, JavaScript/TypeScript, Java, C#, Go
- **Migration tools**: Alembic, Django migrations, Flyway, Liquibase

## 🌐 Multi-Language Documentation

Generate schema documentation in multiple languages:

```bash
# Spanish documentation
python main.py --repo https://github.com/user/repo --language "Spanish"

# Chinese documentation  
python main.py --repo https://github.com/user/repo --language "Chinese"

# French documentation
python main.py --repo https://github.com/user/repo --language "French"
```

The tool will translate:
- Table and column descriptions
- Constraint explanations
- Enum value meanings
- Relationship descriptions
- General documentation text

## 🐳 Running with Docker

To run this project in a Docker container:

1. Build the Docker image
   ```bash
   docker build -t schema-generator .
   ```

2. Run the container with your API key:
   ```bash
   docker run -it --rm \
     -e GEMINI_API_KEY="YOUR_API_KEY_HERE" \
     -v "$(pwd)/output_schemas":/app/output \
     schema-generator --repo https://github.com/username/repo
   ```

## 🛠 How It Works

The tool uses a sophisticated AI-powered pipeline:

1. **📁 FetchRepo**: Crawls the codebase for relevant files (models, migrations, schemas)
2. **🔍 IdentifyTables**: Uses AI to find database tables and model definitions
3. **🔗 AnalyzeTableRelationships**: Discovers foreign keys and table relationships
4. **📊 OrderTables**: Determines logical order for documentation (dependencies first)
5. **📝 WriteTableSchemas**: Generates detailed schema documentation for each table
6. **📚 CombineSchemas**: Creates comprehensive documentation site with ER diagrams

## 💡 Development and Architecture

This project is built using [Pocket Flow](https://github.com/The-Pocket/PocketFlow), a lightweight LLM framework that enables rapid AI application development. The transformation from tutorial generation to schema documentation demonstrates the flexibility of the flow-based architecture.

### Key Components:

- **Flow-based Architecture**: Modular nodes connected in a pipeline
- **AI-Powered Analysis**: Large language models understand code structure
- **Incremental Processing**: Each table processed separately for detailed analysis
- **Relationship Mapping**: Automatic discovery of foreign key relationships
- **Multi-format Output**: Markdown documentation with Mermaid diagrams

## 🤝 Contributing

We welcome contributions! Some areas where you can help:

- **Database support**: Add support for new database technologies
- **Output formats**: Generate JSON, OpenAPI specs, or other formats
- **Analysis improvements**: Better detection of constraints and relationships
- **Documentation quality**: Improve the generated documentation templates
- **Performance**: Optimize for large codebases

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built on [Pocket Flow](https://github.com/The-Pocket/PocketFlow) framework
- Inspired by the original [AI Codebase Knowledge Builder](https://github.com/The-Pocket/Tutorial-Codebase-Knowledge)
- Uses advanced language models for code understanding