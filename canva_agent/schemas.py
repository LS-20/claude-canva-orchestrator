"""Pydantic models for the Phase 1 design spec."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Color(BaseModel):
    hex: str
    role: str


class TypographyElement(BaseModel):
    text: str
    font_family_guess: str
    size_estimate: str
    weight: Literal["light", "regular", "medium", "bold"]
    color_hex: str


class StockAssetQuery(BaseModel):
    purpose: str
    canva_search_query: str
    style_notes: str


class LayoutNote(BaseModel):
    grid: str
    alignment: str
    spacing_density: Literal["tight", "balanced", "airy"]
    focal_point: str


class DesignSpec(BaseModel):
    design_type: str
    dimensions_estimate: str
    mood: str
    color_palette: list[Color]
    typography: list[TypographyElement]
    components: list[str]
    stock_asset_queries: list[StockAssetQuery]
    layout: LayoutNote
    composition_notes: str
    uncertainties: list[str] = Field(default_factory=list)
