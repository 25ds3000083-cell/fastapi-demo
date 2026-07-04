from src.fastapi_demo.main import app
from mangum import Mangum

handler = Mangum(app)
