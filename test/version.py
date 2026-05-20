import importlib
import pkg_resources

# ---- Your extracted module list (cleaned manually) ----
modules = {
    "os",
    "pathlib",
    "fastapi",
    "starlette",
    "dotenv",
    "secrets",
    "smtplib",
    "datetime",
    "email",
    "bcrypt",
    "mysql",
    "json",
    "numpy",
    "pandas",
    "joblib",
    "scipy",
    "sklearn",
    "io",
    "base64",
    "matplotlib",
    "seaborn",
    "plotly",
}

# ---- Function to get version ----
def get_version(module_name):
    try:
        # Try pkg_resources (works for most installed packages)
        return pkg_resources.get_distribution(module_name).version
    except:
        try:
            # Try import and check __version__
            module = importlib.import_module(module_name)
            return getattr(module, "__version__", None)
        except:
            return None

# ---- Main logic ----
print("\nInstalled Modules & Versions:\n")

for module in sorted(modules):
    version = get_version(module)
    
    if version:
        print(f"{module} -- {version}")
    else:
        print(module)