# run_scraper.py
import time
import traceback
from datetime import datetime, timezone
import os
import sys
# Import the specific module loading tool
import importlib.util 

# --- Configuration ---
# Scraper interval (How often scrape_strikes.py runs).
# Running too frequently (e.g., < 30s) is generally wasteful and adds load.
# The map updates its *display* faster (e.g., every 12s), fetching the *latest saved file*.
RUN_INTERVAL_SECONDS = 10 

# Get the directory of the current script (run_scraper.py)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# The NAME of your scraper script file
SCRAPER_FILE_NAME = "scrape_strikes_europe.py" 
SCRAPER_FILE_PATH = os.path.join(SCRIPT_DIR, SCRAPER_FILE_NAME)

# --- Import the scraper module and its function/variables dynamically ---
scraper_module = None # Variable to hold the loaded module
run_scrape_and_update = None # Variable to hold the main function
SCRAPER_DATA_FILE = "unknown" # Variable to hold the DATA_FILE path from the scraper

try:
    # Load the module specification from the file path
    spec = importlib.util.spec_from_file_location(SCRAPER_FILE_NAME.replace('.py', ''), SCRAPER_FILE_PATH)
    if spec is None:
         raise FileNotFoundError(f"Could not find module spec for {SCRAPER_FILE_NAME} at {SCRAPER_FILE_PATH}")

    # Create a module object
    scraper_module = importlib.util.module_from_spec(spec)
    
    # Add the module to sys.modules (needed for absolute imports within the scraper itself, if any)
    # Use the spec name (filename without .py) as the module name
    sys.modules[spec.name] = scraper_module 
    
    # Execute the module's code
    spec.loader.exec_module(scraper_module)

    # Now, access the function and variable from the loaded module object
    if hasattr(scraper_module, 'run_scrape_and_update'):
         run_scrape_and_update = scraper_module.run_scrape_and_update
    else:
         raise AttributeError(f"Function 'run_scrape_and_update' not found in {SCRAPER_FILE_NAME}")

    if hasattr(scraper_module, 'DATA_FILE'):
         SCRAPER_DATA_FILE = scraper_module.DATA_FILE
    else:
         print(f"Warning: Variable 'DATA_FILE' not found in {SCRAPER_FILE_NAME}. Print message will be inaccurate.")


except FileNotFoundError as e:
     print(f"---! ERROR !---")
     print(e)
     print(f"Please ensure '{SCRAPER_FILE_NAME}' exists in the same directory as '{os.path.basename(__file__)}'.")
     exit()
except (ImportError, AttributeError) as e:
    print(f"---! ERROR during scraper import !---")
    print(f"Could not import required components from '{SCRAPER_FILE_NAME}'. Error: {e}")
    traceback.print_exc()
    exit()
except Exception as e:
     print(f"---! UNEXPECTED ERROR during scraper import/initialization !---")
     print(f"An unexpected error occurred while loading '{SCRAPER_FILE_NAME}': {e}")
     traceback.print_exc()
     exit()

# --- Main Loop ---
if __name__ == "__main__":
    # Ensure we successfully loaded the function before trying to run
    if run_scrape_and_update is None:
        print("---! Cannot start runner loop due to previous import errors. !---")
        exit()

    print("--- Starting Automated Scraper Runner (Worldwide Focus) ---")
    print(f"The scraper '{SCRAPER_FILE_NAME}' will run every {RUN_INTERVAL_SECONDS} seconds.")
    print(f"It is configured to save data to: {SCRAPER_DATA_FILE}") # Referencing the variable from the scraper module
    print("Press Ctrl+C to stop.")

    # Check if the directory for the data file exists before starting the loop
    data_dir = os.path.dirname(SCRAPER_DATA_FILE)
    if data_dir and not os.path.exists(data_dir):
        try:
            print(f"Creating data directory: {data_dir}")
            os.makedirs(data_dir, exist_ok=True)
        except OSError as e:
             print(f"---! ERROR !---")
             print(f"Could not create data directory {data_dir}: {e}")
             print("Please create the directory manually or check permissions.")
             # Exit gracefully as saving will fail anyway
             exit()


    while True:
        start_cycle_time = time.time() # Record start time for the interval

        try:
            # Execute the main logic from the scraper script
            run_scrape_and_update()

        except Exception as e:
            # Log any unexpected errors that happen *within* the scraper's execution
            print(f"\n---! UNEXPECTED ERROR during scrape cycle !---")
            print(f"Time: {datetime.now(timezone.utc).isoformat()}")
            print(f"Error Type: {type(e).__name__}")
            print(f"Error Message: {e}")
            print("Traceback:")
            traceback.print_exc() # Print the full traceback
            print("---! Continuing after error... !---\n")
            # Continue the loop even if one run fails

        # Wait for the next interval - ensures the loop takes at least RUN_INTERVAL_SECONDS
        # This is the pause *between* scrape jobs.
        end_cycle_time = time.time()
        elapsed_time = end_cycle_time - start_cycle_time
        wait_time = RUN_INTERVAL_SECONDS - elapsed_time

        if wait_time > 0:
             print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S Z')}] Waiting {wait_time:.2f} seconds for next cycle...\n")
             time.sleep(wait_time)
        else:
             # If elapsed time is longer than interval (e.g., scraping took too long), don't wait
             print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S Z')}] Cycle took longer than {RUN_INTERVAL_SECONDS}s ({elapsed_time:.2f}s). Starting next cycle immediately.\n")