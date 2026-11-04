"""Synthetic fixtures only. No camera/model output or personal data."""

from .models import Item, Placement, Scene, Shelf, Size


def demo_scene() -> Scene:
    rows = [
        ("books", "参考书", "学习", 180, 160, 240, "lower", 30, 80, False),
        ("camera", "相机收纳盒", "数码", 220, 160, 130, "lower", 300, 150, True),
        ("cables", "线材盒", "数码", 160, 120, 90, "lower", 620, 220, True),
        ("stationery", "文具盒", "学习", 200, 90, 70, "upper", 80, 190, True),
        ("headphones", "耳机盒", "数码", 180, 160, 100, "upper", 390, 100, True),
        ("supplies", "日用品盒", "生活", 160, 140, 180, "upper", 650, 200, True),
    ]
    return Scene(
        id="demo-room",
        name="书桌旁的收纳柜",
        version=1,
        shelves=[
            Shelf(
                id="lower", name="下层", size=Size(width=900, depth=400, height=300), elevation=40
            ),
            Shelf(
                id="upper", name="上层", size=Size(width=900, depth=400, height=300), elevation=380
            ),
        ],
        items=[
            Item(
                id=i,
                name=n,
                category=c,
                size=Size(width=w, depth=d, height=h),
                placement=Placement(shelf_id=s, x=x, y=y),
                movable=m,
            )
            for i, n, c, w, d, h, s, x, y, m in rows
        ],
    )
