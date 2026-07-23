"""终端二维码渲染（HC-QR-3）。

把 `begin_login` 已经截好的二维码 PNG 解码出原始内容，再重新编码成一段可以
直接粘贴进聊天回复、在等宽字体终端里正常显示的纯文本二维码（Unicode 半块
字符，每行对应二维码的两行像素）。

放在服务端而不是让调用方自己写 shell 脚本：调用方是 LLM agent，此前既抄错
过超长的 base64（丢字符导致 padding 错误），也遇到过运行环境里没装
chafa/zbarimg/qrencode 这些系统工具的情况。解码/重编码只依赖两个纯逻辑库
（pyzbar 需要系统 libzbar0 动态库，qrcode 不需要任何系统依赖），全部在这一个
进程里做完，调用方只需要转发一段文本，不需要自己拼命令、也不需要环境里有
任何终端图像工具。
"""
from __future__ import annotations

import io


class QRDecodeError(Exception):
    """二维码截图无法解出内容（可能截到了空白/未渲染完成的图片）。"""


def decode_qr_payload(png_bytes: bytes) -> str:
    """从二维码 PNG 截图里解出原始编码内容（通常是站点的扫码跳转 URL）。"""
    from PIL import Image
    from pyzbar.pyzbar import decode as zbar_decode

    image = Image.open(io.BytesIO(png_bytes))
    results = zbar_decode(image)
    if not results:
        raise QRDecodeError("未能从图片中识别出二维码内容。")
    return results[0].data.decode("utf-8", errors="replace")


def render_ascii_qr(payload: str) -> str:
    """把内容重新编码为终端可直接显示的二维码文本。"""
    import qrcode

    qr = qrcode.QRCode(border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    matrix = qr.get_matrix()

    lines = []
    for y in range(0, len(matrix), 2):
        top = matrix[y]
        bottom = matrix[y + 1] if y + 1 < len(matrix) else [False] * len(top)
        chars = []
        for is_top_dark, is_bottom_dark in zip(top, bottom):
            if is_top_dark and is_bottom_dark:
                chars.append("█")
            elif is_top_dark:
                chars.append("▀")
            elif is_bottom_dark:
                chars.append("▄")
            else:
                chars.append(" ")
        lines.append("".join(chars))
    return "\n".join(lines)
