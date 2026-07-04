from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse  # noqa: F401
from time import perf_counter
from uuid import uuid4

app = FastAPI()

ALLOWED_ORIGINS = ["https://dash-lnxsv8.example.com"]
YOUR_EMAIL = "25ds3000083@ds.study.iitm.ac.in"  # replace with your real logged-in email

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_headers(request: Request, call_next):
    start = perf_counter()
    request_id = str(uuid4())

    response = await call_next(request)

    process_time = max(perf_counter() - start, 0.0)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time"] = f"{process_time:.6f}"
    return response


@app.get("/stats")
async def stats(values: str):
    nums = [int(x.strip()) for x in values.split(",") if x.strip() != ""]
    count = len(nums)
    total = sum(nums)
    minimum = min(nums)
    maximum = max(nums)
    mean = total / count

    return {
        "email": YOUR_EMAIL,
        "count": count,
        "sum": total,
        "min": minimum,
        "max": maximum,
        "mean": round(mean, 2),
    }
