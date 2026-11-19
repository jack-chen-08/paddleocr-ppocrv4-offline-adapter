#!/usr/bin/env python3
"""生成 10 张虚构合同页图片 + 行级标注（ground truth）。

要求（任务原文）：10 张虚构合同页图片及标注文本；全部为虚构合同，不含任何真实
个人信息或企业信息。渲染时故意混用全角/半角数字与标点，用来验证归一化逻辑。

输出：
  data/pages/page_01.png ... page_10.png   （200 dpi，A4）
  data/labels.json                          （每页行文本，印章环形文字不计入正文）
  data/stamps.json                          （每页印章区域，供评估参考）

用法：python tools/gen_test_pages.py
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data"

W, H = 1654, 2339  # A4 @ 200dpi
MARGIN_X, MARGIN_TOP = 150, 160
LINE_GAP = 58
FONT_PATHS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]

SELLERS = ["蓝湾智造科技有限公司", "启衡商务服务有限公司", "南屿数据科技有限公司", "沐石供应链有限公司"]
BUYERS = ["星澜产业园管理有限公司", "恒沐商务咨询有限公司", "青禾空间运营有限公司"]
ITEMS = [
    ("产业资源对接服务", 128000),
    ("会员数据中台实施", 356000),
    ("知识库与 SOP 工作台", 214500),
    ("招商漏斗看板定制", 98000),
    ("小程序会员端开发", 176800),
]

CLAUSES = [
    "第一条 服务内容与交付标准。乙方按附件一《服务清单》向甲方提供服务，交付物应满足附件二的技术与验收要求。",
    "第二条 合同价款。本合同总价为人民币 １２８，０００.００ 元（含税），价款支付节点见第三条。",
    "第三条 付款方式。合同生效后 5 个工作日内甲方支付 30%；阶段验收通过后 10 个工作日内支付 60%；质保期满支付 10%。",
    "第四条 交付周期。乙方应于 2026 年 3 月 31 日前完成全部交付；因甲方原因导致的延误，交付期相应顺延。",
    "第五条 验收标准。甲方应在收到交付物后 10 个工作日内完成验收；逾期未提出书面异议的，视为验收通过。",
    "第六条 知识产权。定制开发成果的著作权归甲方所有；乙方保留其通用组件、工具与既有技术的权利。",
    "第七条 保密义务。双方对合作中知悉的商业秘密、会员数据承担保密义务，保密期限为合同终止后 3 年。",
    "第八条 数据合规。乙方处理会员数据应遵循最小必要原则，不得将数据传输至境外，不得用于本合同以外用途。",
    "第九条 违约责任。任何一方违约，应向守约方支付合同总价 5% 的违约金；损失超过违约金的，按实际损失赔偿。",
    "第十条 争议解决。因本合同发生的争议，双方应友好协商；协商不成的，提交合同签订地人民法院诉讼解决。",
    "第十一条 其他约定。本合同一式肆份，甲乙双方各执贰份，自双方盖章之日起生效。",
]

SIG_LINES = [
    "甲方（盖章）：星澜产业园管理有限公司",
    "授权代表（签字）：＿＿＿＿＿＿＿＿",
    "签署日期：2026 年 1 月 12 日",
    "乙方（盖章）：蓝湾智造科技有限公司",
    "授权代表（签字）：＿＿＿＿＿＿＿＿",
    "签署日期：2026 年 1 月 12 日",
]

STAMP_TEXTS = ["合同专用章", "蓝湾智造科技有限公司", "星澜产业园管理有限公司"]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    raise SystemExit("未找到中文字体，请安装 fonts-noto-cjk")


def _draw_stamp(img: Image.Image, cx: int, cy: int, radius: int, org: str, angle_seed: int) -> dict:
    """画一个虚构的红色公章：外环 + 环形公司名 + 中心横排「合同专用章」。"""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    red = (200, 20, 25, 210)
    d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=red, width=7)
    d.ellipse([cx - radius + 16, cy - radius + 16, cx + radius - 16, cy + radius - 16], outline=red, width=2)

    # 环形文字：逐字旋转排布
    import math

    text = org
    n = len(text)
    start = -160 + angle_seed % 20
    span = 200
    for i, ch in enumerate(text):
        ang = math.radians(start + span * i / max(n - 1, 1))
        tx = cx + (radius - 34) * math.sin(ang)
        ty = cy - (radius - 34) * math.cos(ang)
        f = _font(30)
        tmp = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
        ImageDraw.Draw(tmp).text((30, 30), ch, font=f, fill=red, anchor="mm")
        tmp = tmp.rotate(-math.degrees(ang), resample=Image.BICUBIC)
        layer.alpha_composite(tmp, (int(tx) - 30, int(ty) - 30))

    # 中心横排字（也是印章内容，不属于正文）
    ImageDraw.Draw(layer).text(
        (cx, cy + radius * 0.35), "合同专用章", font=_font(34), fill=red, anchor="mm"
    )
    img.alpha_composite(layer)
    return {"cx": cx, "cy": cy, "r": radius}


def build_page(idx: int, rng: random.Random) -> tuple[Image.Image, list[str], dict | None]:
    img = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    title_font, body_font, small_font = _font(46), _font(30), _font(26)

    seller = SELLERS[idx % len(SELLERS)]
    buyer = BUYERS[idx % len(BUYERS)]
    item, amount = ITEMS[idx % len(ITEMS)]
    contract_no = f"HT-2026-{idx:03d}"

    d.text((W // 2, MARGIN_TOP), "产业资源对接服务合同", font=title_font, fill=(0, 0, 0), anchor="ma")
    d.text((W // 2, MARGIN_TOP + 70), f"合同编号：{contract_no}", font=small_font, fill=(60, 60, 60), anchor="ma")

    lines: list[str] = ["产业资源对接服务合同", f"合同编号：{contract_no}"]
    y = MARGIN_TOP + 150
    header = [
        f"甲方（委托方）：{buyer}",
        f"乙方（服务方）：{seller}",
        f"服务事项：{item}",
    ]
    for h in header:
        d.text((MARGIN_X, y), h, font=body_font, fill=(0, 0, 0))
        lines.append(h)
        y += LINE_GAP

    y += 10
    start = (idx * 2) % len(CLAUSES)
    body = [CLAUSES[(start + i) % len(CLAUSES)] for i in range(6)]
    if idx % 3 == 0:
        body.insert(2, f"补充约定：合同总价按人民币 {amount:,}.00 元执行，分（３）期支付。")
    for b in body:
        # 自动折行
        cur = ""
        for ch in b:
            if d.textlength(cur + ch, font=body_font) > W - 2 * MARGIN_X:
                d.text((MARGIN_X, y), cur, font=body_font, fill=(0, 0, 0))
                lines.append(cur)
                y += LINE_GAP
                cur = ch
            else:
                cur += ch
        if cur:
            d.text((MARGIN_X, y), cur, font=body_font, fill=(0, 0, 0))
            lines.append(cur)
            y += LINE_GAP

    stamp = None
    sig = [
        f"甲方（盖章）：{buyer}",
        "授权代表（签字）：",
        "签署日期：2026 年 1 月 12 日",
        f"乙方（盖章）：{seller}",
        "授权代表（签字）：",
        "签署日期：2026 年 1 月 12 日",
    ]
    y = H - 620
    for s in sig:
        d.text((MARGIN_X, y), s, font=small_font, fill=(0, 0, 0))
        lines.append(s)
        y += 46
    if idx % 3 == 0:  # 每 3 页有一页在签署区盖章，印章只压住行尾 2-3 字
        stamp = _draw_stamp(img, MARGIN_X + 520, H - 380, 150, seller, idx)

    d.text((W // 2, H - 90), f"第 {idx} 页 / 共 10 页", font=small_font, fill=(80, 80, 80), anchor="ma")
    lines.append(f"第 {idx} 页 / 共 10 页")
    return img, lines, stamp


def main() -> None:
    rng = random.Random(20261119)
    (OUT / "pages").mkdir(parents=True, exist_ok=True)
    labels: dict[str, dict] = {}
    stamps: dict[str, dict] = {}
    for idx in range(1, 11):
        img, lines, stamp = build_page(idx, rng)
        name = f"page_{idx:02d}.png"
        img.convert("RGB").save(OUT / "pages" / name, dpi=(200, 200))
        labels[name] = {"page_no": idx, "width": W, "height": H, "lines": lines}
        if stamp:
            stamps[name] = stamp
    (OUT / "labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "stamps.json").write_text(json.dumps(stamps, ensure_ascii=False, indent=1), encoding="utf-8")
    total_lines = sum(len(v["lines"]) for v in labels.values())
    print(f"生成 {len(labels)} 页，共 {total_lines} 行标注；带印章页 {len(stamps)} 张")


if __name__ == "__main__":
    main()
