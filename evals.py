from evals import EVAL_JOBS
import asyncio

async def main():
    # Run all registered evals at once.
    await asyncio.gather(*(eval_job() for eval_job in EVAL_JOBS))


if __name__ == "__main__":
    asyncio.run(main())
