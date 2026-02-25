#!/usr/bin/env python3
"""Trendyol Seller Panel satış verisini çekip maliyet hesaplama.

Kullanım:
  1) `pip install playwright`
  2) `playwright install chromium`
  3) `python trendyol_sales_report.py --start 2026-01-01 --end 2026-01-31 --costs urun_maliyet.csv`

Notlar:
- İlk açılışta giriş işlemini (SMS/2FA dahil) tarayıcıda siz tamamlarsınız.
- Script, Sales API çağrısını yakalar; model kodu + net satış adetini çıkarır.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, Page


SALES_ENDPOINT_HINTS = (
    "sales",
    "operasyon",
    "report",
    "siparis",
)


@dataclass
class SaleRow:
    model_code: str
    net_quantity: int


def _to_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    value = str(value).strip().replace(".", "").replace(",", ".")
    try:
        return int(float(value))
    except ValueError:
        return 0


def normalize_row(item: dict[str, Any]) -> SaleRow | None:
    """Farklı API şemaları için model kodu + net satış adedi alanlarını normalize eder."""
    model_code = (
        item.get("modelCode")
        or item.get("model_code")
        or item.get("stockCode")
        or item.get("barcode")
        or ""
    )
    net_quantity = (
        item.get("netSalesCount")
        or item.get("netSalesQuantity")
        or item.get("net_quantity")
        or item.get("netOrderCount")
        or item.get("quantity")
        or 0
    )

    model_code = str(model_code).strip()
    if not model_code:
        return None

    return SaleRow(model_code=model_code, net_quantity=_to_int(net_quantity))


def parse_sales_payload(payload: Any) -> list[SaleRow]:
    """API response içinden satış satırlarını bulur."""
    buckets: list[dict[str, Any]] = []

    if isinstance(payload, dict):
        for key in ("data", "items", "content", "results", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                buckets.extend(x for x in value if isinstance(x, dict))
        if not buckets:
            buckets.extend(x for x in payload.values() if isinstance(x, dict))
    elif isinstance(payload, list):
        buckets.extend(x for x in payload if isinstance(x, dict))

    rows: list[SaleRow] = []
    for item in buckets:
        row = normalize_row(item)
        if row:
            rows.append(row)
    return rows


def merge_rows(rows: list[SaleRow]) -> list[SaleRow]:
    merged: dict[str, int] = {}
    for row in rows:
        merged[row.model_code] = merged.get(row.model_code, 0) + row.net_quantity
    return [SaleRow(model_code=k, net_quantity=v) for k, v in sorted(merged.items())]


def read_costs(path: Path) -> dict[str, float]:
    """CSV format: model_code,cost_per_unit"""
    costs: dict[str, float] = {}
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = str(row.get("model_code", "")).strip()
            if not code:
                continue
            value = str(row.get("cost_per_unit", "0")).replace(",", ".")
            try:
                costs[code] = float(value)
            except ValueError:
                costs[code] = 0.0
    return costs


def write_output(path: Path, rows: list[SaleRow], costs: dict[str, float] | None) -> tuple[float, int]:
    total_cost = 0.0
    total_qty = 0

    headers = ["model_code", "net_sales_quantity"]
    if costs is not None:
        headers.extend(["cost_per_unit", "total_cost"])

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()

        for row in rows:
            total_qty += row.net_quantity
            rec = {
                "model_code": row.model_code,
                "net_sales_quantity": row.net_quantity,
            }

            if costs is not None:
                cpu = costs.get(row.model_code, 0.0)
                tcost = cpu * row.net_quantity
                total_cost += tcost
                rec["cost_per_unit"] = f"{cpu:.2f}"
                rec["total_cost"] = f"{tcost:.2f}"

            writer.writerow(rec)

    return total_cost, total_qty


def looks_like_sales_url(url: str) -> bool:
    lowered = url.lower()
    return all(hint in lowered for hint in ("sat",)) and any(h in lowered for h in SALES_ENDPOINT_HINTS)


async def collect_rows(page: Page, start_date: str, end_date: str) -> list[SaleRow]:
    responses: list[list[SaleRow]] = []

    async def on_response(resp):
        try:
            if resp.request.method != "GET":
                return
            if not looks_like_sales_url(resp.url):
                return
            body = await resp.text()
            payload = json.loads(body)
            rows = parse_sales_payload(payload)
            if rows:
                responses.append(rows)
        except Exception:
            return

    page.on("response", on_response)

    await page.goto("https://partner.trendyol.com", wait_until="domcontentloaded")
    print("Tarayıcı açıldı. Giriş yapın ve Satış & Operasyon > Satış sayfasına gidin.")
    print(f"Tarih aralığını {start_date} - {end_date} seçip raporu yükleyin.")
    input("Hazır olduğunda burada Enter'a basın...")

    await page.wait_for_timeout(3000)

    all_rows: list[SaleRow] = []
    for chunk in responses:
        all_rows.extend(chunk)

    if not all_rows:
        print("Uyarı: API cevabı yakalanamadı. Sayfayı yenileyip tekrar deneyin.")
    return merge_rows(all_rows)


async def run(start_date: str, end_date: str, output: Path, costs_path: Path | None) -> None:
    costs = read_costs(costs_path) if costs_path else None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        rows = await collect_rows(page, start_date, end_date)

        await context.close()
        await browser.close()

    if not rows:
        print("Satır bulunamadı, dosya yazılmadı.")
        return

    total_cost, total_qty = write_output(output, rows, costs)
    print(f"Toplam ürün adedi: {total_qty}")
    print(f"Çıktı dosyası: {output}")
    if costs is not None:
        print(f"Toplam maliyet: {total_cost:.2f} TL")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trendyol satış raporundan model kodu/net satış adedi çekme")
    parser.add_argument("--start", required=True, help="Başlangıç tarihi (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="Bitiş tarihi (YYYY-MM-DD)")
    parser.add_argument("--output", default="trendyol_satis_ozet.csv", help="Çıktı CSV yolu")
    parser.add_argument("--costs", help="Maliyet CSV yolu (model_code,cost_per_unit)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(
        run(
            start_date=args.start,
            end_date=args.end,
            output=Path(args.output),
            costs_path=Path(args.costs) if args.costs else None,
        )
    )
