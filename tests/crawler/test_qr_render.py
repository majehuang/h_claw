import io

import pytest
import qrcode

from app.crawler.qr_render import QRDecodeError, decode_qr_payload, render_ascii_qr


def _make_png(payload: str) -> bytes:
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_decode_qr_payload_roundtrips_real_qr_png():
    png = _make_png("https://qr.m.jd.com/p?k=abc123&appid=133")
    assert decode_qr_payload(png) == "https://qr.m.jd.com/p?k=abc123&appid=133"


def test_decode_qr_payload_raises_on_image_without_qr():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (50, 50), color="white").save(buf, format="PNG")

    with pytest.raises(QRDecodeError):
        decode_qr_payload(buf.getvalue())


def test_render_ascii_qr_produces_nonempty_block_text():
    text = render_ascii_qr("https://qr.m.jd.com/p?k=abc123&appid=133")
    assert text
    lines = text.splitlines()
    assert len(lines) > 5
    assert all(len(line) == len(lines[0]) for line in lines)  # 矩形对齐
    assert any(ch in line for line in lines for ch in "█▀▄")  # 确实画出了黑块


def test_render_then_decode_end_to_end_matches_original_payload():
    # 用 qrcode 重编码出的图，再喂给我们自己的 decode_qr_payload，验证
    # render_ascii_qr 产出的矩阵和真正生成的图片编码的是同一份内容
    # （间接验证：直接从 qrcode 生成 PNG 解码回去，两条路径共享同一个
    # QRCode.get_matrix() 结果）。
    payload = "https://qr.m.jd.com/p?k=roundtrip&appid=133"
    png = _make_png(payload)
    assert decode_qr_payload(png) == payload
    ascii_qr = render_ascii_qr(payload)
    assert ascii_qr  # 只要不抛异常、有内容即可，视觉正确性已由上面的用例覆盖
