from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import Settings

mcp = FastMCP("crawler-mcp")


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def build_asgi_app():
    return mcp.http_app()


def main() -> None:
    settings = Settings()
    if settings.mcp_transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http", host=settings.mcp_host, port=settings.mcp_port)


if __name__ == "__main__":
    main()
