import sys
import subprocess
from pathlib import Path
import traceback

from whatsapp_sender import resolve_window


def get_crawler_args(crawler_file: Path, window: str) -> list[str]:
    try:
        supports_days = "--days" in crawler_file.read_text(encoding="utf-8")
    except OSError:
        supports_days = False

    if not supports_days:
        return []

    days = "2" if window == "morning" else "1"
    return ["--days", days]


def run_crawlers():
    crawler_dir = Path("crawlers")

    if not crawler_dir.exists():
        print(f"❌ Folder not found: {crawler_dir}")
        return False

    crawler_files = sorted(
        crawler_file
        for crawler_file in crawler_dir.glob("*.py")
        if crawler_file.name != "__init__.py"
    )

    if not crawler_files:
        print("⚠️ No crawler files found.")
        return False

    print(f"🚀 Found {len(crawler_files)} crawler(s)\n")

    failed = []
    selected_window = resolve_window("auto")

    for crawler_file in crawler_files:
        print(f"▶ Running: {crawler_file.name}")
        module_name = f"crawlers.{crawler_file.stem}"
        crawler_args = get_crawler_args(crawler_file, selected_window)

        try:
            subprocess.run(
                [sys.executable, "-m", module_name, *crawler_args],
                check=True
            )
            print(f"✅ Success: {crawler_file.name}\n")

        except subprocess.CalledProcessError as e:
            print(f"❌ Failed: {crawler_file.name}")
            print(f"   Exit code: {e.returncode}\n")
            traceback.print_exc()
            failed.append(crawler_file.name)

    print("=" * 50)

    if failed:
        print(f"⚠️ {len(failed)} crawler(s) failed:")
        for f in failed:
            print(f"   - {f}")
        return False

    print("✅ All crawlers completed successfully.")
    return True


def run_whatsapp_sender():
    whatsapp_file = Path("whatsapp_sender.py")

    if not whatsapp_file.exists():
        print("❌ whatsapp_sender.py not found")
        return

    print("\n📱 Running WhatsApp sender...")

    try:
        subprocess.run(
            [sys.executable, str(whatsapp_file)],
            check=True
        )
        print("✅ WhatsApp sender completed.")

    except subprocess.CalledProcessError as e:
        traceback.print_exc()
        print(f"❌ WhatsApp sender failed (exit code {e.returncode})")


def main():
    success = run_crawlers()
    if not success:
        print("\n⛔ Some crawlers failed.")
    run_whatsapp_sender()


if __name__ == "__main__":
    main()
