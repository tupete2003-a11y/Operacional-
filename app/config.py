import os


def get_groq_api_key():
    # Tolerate accidental casing or surrounding spaces in the Render variable name.
    for name, value in os.environ.items():
        if name.strip().upper() == "GROQ_API_KEY":
            return value.strip()
    return ""


def get_groq_env_names():
    # Report names only for safe diagnostics; never return secret values.
    return sorted(name for name in os.environ if "GROQ" in name.upper())
