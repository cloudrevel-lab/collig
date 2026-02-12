import os
import shutil

class Paths:
    def __init__(self):
        self.home = os.path.expanduser("~/.collig")
        self.config_dir = os.path.join(self.home, "configs")
        self.data_dir = os.path.join(self.home, "data")
        self.sessions_dir = os.path.join(self.home, "sessions")
        self.global_config_file = os.path.join(self.home, "config.json")

        self._ensure_dirs()

    def _ensure_dirs(self):
        """Ensures the basic directory structure exists."""
        os.makedirs(self.home, exist_ok=True)
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.sessions_dir, exist_ok=True)

    def get_skill_config_dir(self, skill_name: str) -> str:
        """Returns the configuration directory for a specific skill."""
        # Normalize skill name to be filesystem friendly
        clean_name = skill_name.lower().replace(" ", "_")
        path = os.path.join(self.config_dir, clean_name)
        os.makedirs(path, exist_ok=True)
        return path

    def get_skill_data_dir(self, skill_name: str) -> str:
        """Returns the data directory for a specific skill."""
        clean_name = skill_name.lower().replace(" ", "_")
        path = os.path.join(self.data_dir, clean_name)
        os.makedirs(path, exist_ok=True)
        return path

    def migrate_legacy_data(self):
        """Attempts to migrate data from the current working directory to ~/.collig."""
        cwd = os.getcwd()
        
        # Migrate config.json
        old_config = os.path.join(cwd, "config.json")
        if os.path.exists(old_config) and not os.path.exists(self.global_config_file):
            print(f"Migrating config.json to {self.global_config_file}...")
            shutil.copy2(old_config, self.global_config_file)

        # Migrate sessions
        old_sessions = os.path.join(cwd, "sessions")
        if os.path.exists(old_sessions):
            print(f"Migrating sessions to {self.sessions_dir}...")
            for item in os.listdir(old_sessions):
                s = os.path.join(old_sessions, item)
                d = os.path.join(self.sessions_dir, item)
                if os.path.isfile(s) and not os.path.exists(d):
                    shutil.copy2(s, d)

        # Migrate data directories (memory_db, bookmarks_db, profile_db)
        # Old paths: data/memory_db -> ~/.collig/data/memory_notes/ (mapped manually below) or keep names?
        # Let's map old specific paths to new generalized ones.
        
        # Map: old_rel_path -> new_abs_path
        migrations = {
            "data/memory_db": self.get_skill_data_dir("memory_notes"), # Skill name map
            "data/bookmarks_db": self.get_skill_data_dir("bookmarks"),
            "data/profile_db": self.get_skill_data_dir("personal_profile")
        }

        for old_rel, new_abs in migrations.items():
            old_abs = os.path.join(cwd, old_rel)
            if os.path.exists(old_abs):
                # Copy contents if new dir is empty
                if not os.listdir(new_abs):
                    print(f"Migrating {old_rel} to {new_abs}...")
                    # shutil.copytree requires dest not to exist usually, or use dirs_exist_ok (py3.8+)
                    # Since we created dirs in get_skill_data_dir, we use:
                    for item in os.listdir(old_abs):
                        s = os.path.join(old_abs, item)
                        d = os.path.join(new_abs, item)
                        if os.path.isdir(s):
                            shutil.copytree(s, d, dirs_exist_ok=True)
                        else:
                            shutil.copy2(s, d)

# Singleton instance
paths = Paths()
