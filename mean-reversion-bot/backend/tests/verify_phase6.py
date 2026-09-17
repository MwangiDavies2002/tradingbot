import sys
import os
import asyncio
from datetime import datetime

# Add current directory to path
sys.path.append(os.getcwd() + "/mean-reversion-bot/backend")

from app.bot import BotRunner

async def test_recovery_mode():
    print("Testing Phase 6 Recovery Mode...")
    
    class FailingBotRunner(BotRunner):
        def __init__(self):
            super().__init__()
            self.setup_calls = 0
            self.shutdown_calls = 0
            
        async def _setup(self):
            self.setup_calls += 1
            print(f"  [Mock] Setup attempt {self.setup_calls}")
            if self.setup_calls < 3:
                raise Exception(f"Simulated Setup Failure {self.setup_calls}")
            print("  [Mock] Setup successful")
            
        async def _main_loop(self):
            print("  [Mock] Main loop running. Simulating fatal error...")
            raise Exception("Fatal Error in Main Loop")

        async def _shutdown(self):
            self.shutdown_calls += 1
            print(f"  [Mock] Shutdown called ({self.shutdown_calls})")
            self._running = False

    runner = FailingBotRunner()
    runner._running = True # Simulate start
    
    # We want to check if it retries. 
    # Since it has a 10s delay, we might want to monkeypatch sleep for the test
    import asyncio
    original_sleep = asyncio.sleep
    async def mock_sleep(seconds):
        print(f"  [Mock] Sleeping for {seconds}s (skipped)")
        return
    
    asyncio.sleep = mock_sleep
    
    try:
        # We'll wrap it in a timeout so it doesn't run forever if retry logic is broken
        await asyncio.wait_for(runner.run(), timeout=5)
    except asyncio.TimeoutError:
        print("Test timed out (expected if max retries reached)")
    except Exception as e:
        print(f"Caught expected finish: {e}")
    finally:
        asyncio.sleep = original_sleep

    print(f"Total Setup calls: {runner.setup_calls}")
    print(f"Total Shutdown calls: {runner.shutdown_calls}")
    
    # It should have tried at least 5 times (max_retries)
    assert runner.setup_calls >= 5
    assert runner.shutdown_calls >= 5
    print("DONE: Recovery Mode verified!")

if __name__ == "__main__":
    asyncio.run(test_recovery_mode())
