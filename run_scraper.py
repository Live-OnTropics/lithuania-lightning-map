# run_scraper.py
import time
import traceback
from datetime import datetime, timezone

# Import the main function from your scraper script
try:
    from scrape_strikes import run_scrape_and_update 
except ImportError:
    print("Error: Could not import 'run_scrape_and_update' from scrape_strikes.py.")
    print("Make sure both files are in the same directory.")
    exit()

# --- Configuration ---
RUN_INTERVAL_SECONDS = 60 # How often to run the scraper

# --- Main Loop ---
if __name__ == "__main__":
    print("--- Starting Automated Scraper ---")
    print(f"Scraper will run every {RUN_INTERVAL_SECONDS} seconds.")
    print("Press Ctrl+C to stop.")
    
    while True:
        try:
            run_scrape_and_update() # Execute the main logic from the other file
            
        except Exception as e:
            # Log any unexpected errors during the scrape cycle
            print(f"\n---! UNEXPECTED ERROR in run_scrape_and_update !---")
            print(f"Time: {datetime.now(timezone.utc).isoformat()}")
            print(f"Error Type: {type(e).__name__}")
            print(f"Error Message: {e}")
            print("Traceback:")
            traceback.print_exc() # Print the full traceback
            print("---! Continuing after error... !---\n")
            # Continue the loop even if one run fails

        # Wait for the next interval
        print(f"\n[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S Z')}] Waiting {RUN_INTERVAL_SECONDS} seconds for next cycle...\n")
        time.sleep(RUN_INTERVAL_SECONDS)