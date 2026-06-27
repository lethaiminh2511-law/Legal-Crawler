import sys
import subprocess
from pathlib import Path


def run_crawlers():
    crawler_dir = Path("crawlers")

    if not crawler_dir.exists():
        print(f"❌ Folder not found: {crawler_dir}")
        return False

    crawler_files = sorted(crawler_dir.glob("*.py"))

    if not crawler_files:
        print("⚠️ No crawler files found.")
        return False

    print(f"🚀 Found {len(crawler_files)} crawler(s)\n")

    failed = []

    for crawler_file in crawler_files:
        print(f"▶ Running: {crawler_file.name}")

        try:
            subprocess.run(
                [sys.executable, str(crawler_file)],
                check=True
            )
            print(f"✅ Success: {crawler_file.name}\n")

        except subprocess.CalledProcessError as e:
            print(f"❌ Failed: {crawler_file.name}")
            print(f"   Exit code: {e.returncode}\n")
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
        print(f"❌ WhatsApp sender failed (exit code {e.returncode})")


if __name__ == "__main__":
    success = run_crawlers()
    print("\n⛔ Some crawlers failed.")
    run_whatsapp_sender()