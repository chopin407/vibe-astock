#!/usr/bin/env python3
# mx_data - 妙想金融数据查询 skill
# 基于东方财富妙想API提供金融数据查询能力
# 输出 Excel（多sheet）+ 描述 txt

import os
import sys
import json
import re
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def write_xlsx(file_path: Path, tables: List[Dict[str, Any]]) -> None:
    """Write a small multi-sheet XLSX with only Python's standard library."""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pkg_rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    content_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    ET.register_namespace("", ns)
    ET.register_namespace("r", rel_ns)
    used_names: set[str] = set()
    names: List[str] = []
    for i, table in enumerate(tables, 1):
        base = re.sub(r"[\[\]:*?/\\]", "_", table["sheet_name"]).strip(" '")[:31] or f"表{i}"
        name = base
        suffix = 2
        while name.lower() in used_names:
            tail = f"_{suffix}"
            name = base[: 31 - len(tail)] + tail
            suffix += 1
        used_names.add(name.lower())
        names.append(name)

    def xml_bytes(root: ET.Element) -> bytes:
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def col_name(index: int) -> str:
        name = ""
        while index:
            index, rem = divmod(index - 1, 26)
            name = chr(65 + rem) + name
        return name

    def clean(value: Any) -> str:
        return "".join(ch for ch in flatten_value(value) if ch in "\t\n\r" or ord(ch) >= 32)

    with zipfile.ZipFile(file_path, "w", zipfile.ZIP_DEFLATED) as archive:
        types = ET.Element(f"{{{content_ns}}}Types")
        ET.SubElement(types, f"{{{content_ns}}}Default", Extension="rels", ContentType="application/vnd.openxmlformats-package.relationships+xml")
        ET.SubElement(types, f"{{{content_ns}}}Default", Extension="xml", ContentType="application/xml")
        ET.SubElement(types, f"{{{content_ns}}}Override", PartName="/xl/workbook.xml", ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml")
        for i in range(1, len(tables) + 1):
            ET.SubElement(types, f"{{{content_ns}}}Override", PartName=f"/xl/worksheets/sheet{i}.xml", ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml")
        archive.writestr("[Content_Types].xml", xml_bytes(types))

        root_rels = ET.Element(f"{{{pkg_rel_ns}}}Relationships")
        ET.SubElement(root_rels, f"{{{pkg_rel_ns}}}Relationship", Id="rId1", Type=f"{rel_ns}/officeDocument", Target="xl/workbook.xml")
        archive.writestr("_rels/.rels", xml_bytes(root_rels))

        workbook = ET.Element(f"{{{ns}}}workbook")
        sheets = ET.SubElement(workbook, f"{{{ns}}}sheets")
        book_rels = ET.Element(f"{{{pkg_rel_ns}}}Relationships")
        for i, (table, name) in enumerate(zip(tables, names), 1):
            ET.SubElement(sheets, f"{{{ns}}}sheet", {"name": name, "sheetId": str(i), f"{{{rel_ns}}}id": f"rId{i}"})
            ET.SubElement(book_rels, f"{{{pkg_rel_ns}}}Relationship", Id=f"rId{i}", Type=f"{rel_ns}/worksheet", Target=f"worksheets/sheet{i}.xml")
            worksheet = ET.Element(f"{{{ns}}}worksheet")
            sheet_data = ET.SubElement(worksheet, f"{{{ns}}}sheetData")
            for row_num, row in enumerate([dict(zip(table["fieldnames"], table["fieldnames"]))] + table["rows"], 1):
                xml_row = ET.SubElement(sheet_data, f"{{{ns}}}row", r=str(row_num))
                for col_num, field in enumerate(table["fieldnames"], 1):
                    cell = ET.SubElement(xml_row, f"{{{ns}}}c", r=f"{col_name(col_num)}{row_num}", t="inlineStr")
                    ET.SubElement(ET.SubElement(cell, f"{{{ns}}}is"), f"{{{ns}}}t").text = clean(row.get(field, ""))
            archive.writestr(f"xl/worksheets/sheet{i}.xml", xml_bytes(worksheet))
        archive.writestr("xl/workbook.xml", xml_bytes(workbook))
        archive.writestr("xl/_rels/workbook.xml.rels", xml_bytes(book_rels))
        archive.writestr("docProps/core.xml", b'<?xml version="1.0" encoding="UTF-8"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"/>')

def safe_filename(s: str, max_len: int = 80) -> str:
    """Convert query string to safe filename """
    s = re.sub(r'[<>:"/\\|?*\[\]]', "_", s)
    s = s.strip().replace(" ", "_")[:max_len]
    return s or "query"

def flatten_value(v: Any) -> str:
    """Flatten any value to string """
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)

def ordered_keys(table: Dict[str, Any], indicator_order: List[Any]) -> List[Any]:
    """Order keys """
    data_keys = [k for k in table.keys() if k != "headName"]
    key_map = {str(k): k for k in data_keys}
    preferred: List[Any] = []
    seen: set[str] = set()
    for key in indicator_order:
        key_str = str(key)
        if key_str in key_map and key_str not in seen:
            preferred.append(key_map[key_str])
            seen.add(key_str)
    for key in data_keys:
        key_str = str(key)
        if key_str not in seen:
            preferred.append(key)
            seen.add(key_str)
    return preferred

def normalize_values(raw_values: List[Any], expected_len: int) -> List[str]:
    """Normalize values length """
    values = [flatten_value(v) for v in raw_values]
    if len(values) < expected_len:
        values.extend([""] * (expected_len - len(values)))
    return values[:expected_len]

def return_code_map(block: Dict[str, Any]) -> Dict[str, str]:
    """Get return code map"""
    for key in ("returnCodeMap", "returnCodeNameMap", "codeMap"):
        data = block.get(key)
        if isinstance(data, dict):
            return {str(k): flatten_value(v) for k, v in data.items()}
    return {}

def format_indicator_label(key: str, name_map: Dict[str, Any], code_map: Dict[str, str]) -> str:
    """Format indicator label"""
    mapped = name_map.get(key)
    if mapped is None and key.isdigit():
        mapped = name_map.get(int(key))
    if mapped not in (None, ""):
        return flatten_value(mapped)
    mapped_code = code_map.get(key)
    if mapped_code not in (None, ""):
        return flatten_value(mapped_code)
    if key.isdigit():
        return ""
    return key

def table_to_rows(block: Dict[str, Any]) -> Tuple[List[Dict[str, str]], List[str]]:
    """
    Convert table to rows - adapted for MX API format:
    MX API format: headName is date array, each indicator is an array matching headName length
    This is DATE-ON-ROW format, each row is a date
    """
    table = block.get("table") or {}
    name_map = block.get("nameMap") or {}
    if isinstance(name_map, list):
        name_map = {str(i): v for i, v in enumerate(name_map)}
    elif not isinstance(name_map, dict):
        name_map = {}

    if not isinstance(table, dict):
        # Fallback for generic tables
        if isinstance(table, list):
            if not table:
                return [], []
            if isinstance(table[0], dict):
                rows = table
            else:
                rows = [
                    dict(zip([f"column_{i}" for i in range(len(table[0]))], row))
                    for row in table
                ]
        else:
            return [], []
        return [{name_map.get(k, k): flatten_value(v) for k, v in row.items()} for row in rows], list(rows[0].keys())

    headers = table.get("headName") or []
    if not isinstance(headers, list):
        headers = []
    order = ordered_keys(table, block.get("indicatorOrder") or [])
    entity_name = flatten_value(block.get("entityName") or "") or "指标"
    code_map = return_code_map(block)

    rows: List[Dict[str, str]] = []
    data_key_count = len([key for key in table.keys() if key != "headName"])

    # MX API format: headName is the date column (one row = one date)
    # headName = [date1, date2, date3, ...]
    # indicator = [val1, val2, val3, ...]
    # So each row is a date with all indicator values
    if len(headers) > 0:  # has dates (one date per row)
        fieldnames = ["date"]  # first column is date from headName
        for key in order:
            if key != "headName":
                label = format_indicator_label(str(key), name_map, code_map)
                if label:  # only add non-empty labels
                    fieldnames.append(label)
        
        # Build one row per date
        for row_idx, date in enumerate(headers):
            row = {"date": flatten_value(date)}
            for key in order:
                if key == "headName":
                    continue
                label = format_indicator_label(str(key), name_map, code_map)
                if not label:
                    continue
                raw_values = table.get(key, [])
                value = raw_values[row_idx] if row_idx < len(raw_values) else ""
                row[label] = flatten_value(value)
            rows.append(row)
        
        return rows, fieldnames

    if len(headers) == 1 and data_key_count >= 1:
        # Single date (current quote)
        fieldnames = [entity_name, flatten_value(headers[0])]
        for key in order:
            raw_values = table.get(key, [])
            value = raw_values[0] if isinstance(raw_values, list) and raw_values else raw_values
            label = format_indicator_label(str(key), name_map, code_map)
            rows.append({fieldnames[0]: label, fieldnames[1]: flatten_value(value)})
        return rows, fieldnames

    # Fallback
    return [], []

class MXData:
    """妙想金融数据查询客户端"""
    
    BASE_URL = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"
    
    def __init__(self, api_key: Optional[str] = None):
        """
        初始化客户端
        :param api_key: MX API Key，如果不提供则从环境变量 MX_APIKEY 读取
        """
        self.api_key = api_key or os.getenv("MX_APIKEY")
        if not self.api_key:
            raise ValueError(
                "MX_APIKEY 环境变量未设置，请先设置环境变量：\n"
                "export MX_APIKEY=your_api_key_here\n"
                "或者在初始化时传入 api_key 参数"
            )
    
    def query(self, tool_query: str) -> Dict[str, Any]:
        """
        查询金融数据
        :param tool_query: 自然语言查询问句，如 "东方财富最新价"
        :return: API 响应结果
        """
        headers = {
            "Content-Type": "application/json",
            "apikey": self.api_key
        }
        data = {
            "toolQuery": tool_query
        }
        
        request = Request(
            self.BASE_URL,
            data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"妙想接口 HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"无法连接妙想接口: {exc.reason}") from exc
    
    @staticmethod
    def parse_result(result: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str], int, Optional[str]]:
        """
        Parse API result into tables for Excel output
        :return: (tables, condition_parts, total_rows, error)
            tables: [{"sheet_name": str, "rows": list[dict], "fieldnames": list[str]}]
        """
        status = result.get("status")
        message = result.get("message", "")
        if status != 0:
            return [], [], 0, f"顶层错误: 状态码 {status} - {message}"
        
        data = result.get("data", {})
        inner_data = data.get("data", {})
        search_result = inner_data.get("searchDataResultDTO", {})
        dto_list = search_result.get("dataTableDTOList", [])
        
        if not dto_list:
            return [], [], 0, "接口返回中无 dataTableDTOList"
        
        condition_parts: List[str] = []
        tables: List[Dict[str, Any]] = []
        total_rows = 0
        
        for i, dto in enumerate(dto_list):
            if not isinstance(dto, dict):
                continue
            
            sheet_name = safe_filename(
                dto.get("title") or dto.get("inputTitle") or dto.get("entityName") or f"表{i + 1}"
            )
            condition = dto.get("condition")
            if condition is not None and condition != "":
                entity = dto.get("entityName") or sheet_name
                condition_parts.append(f"[{entity}]\n{condition}")
            
            rows, fieldnames = table_to_rows(dto)
            if not rows:
                continue
            tables.append({"sheet_name": sheet_name, "rows": rows, "fieldnames": fieldnames})
            total_rows += len(rows)
        
        if not tables:
            return [], condition_parts, 0, "dataTableDTOList 中无有效 table 数据"
        return tables, condition_parts, total_rows, None
    
    @staticmethod
    def format_terminal(result: Dict[str, Any], tables: List[Dict[str, Any]], total_rows: int) -> str:
        """Format result for terminal display"""
        output = []
        status = result.get("status")
        message = result.get("message", "")
        if status != 0:
            output.append(f"**错误**: 状态码 {status} - {message}")
            return "\n".join(output)
        
        data = result.get("data", {})
        inner_data = data.get("data", {})
        search_result = inner_data.get("searchDataResultDTO", {})
        entity_tags = search_result.get("entityTagDTOList", [])
        
        if entity_tags:
            output.append("**查询证券**:")
            entities = []
            for tag in entity_tags:
                name = tag.get("fullName", "")
                code = tag.get("secuCode", "")
                type_name = tag.get("entityTypeName", "")
                entities.append(f"- {name} ({code}) - {type_name}")
            output.append("\n".join(entities))
            output.append("")
        
        output.append(f"**查询结果**: {len(tables)} 个表，共 {total_rows} 行数据\n")
        
        # Only preview first 20 rows of first table on terminal
        if tables:
            first = tables[0]
            output.append(f"**{first['sheet_name']}** (前20行预览):\n")
            rows = first["rows"][:20]
            if rows:
                fieldnames = first["fieldnames"]
                output.append("| " + " | ".join(fieldnames) + " |")
                output.append("| " + " | ".join(["---"] * len(fieldnames)) + " |")
                for row in rows:
                    cells = [str(row.get(f, "")) for f in fieldnames]
                    output.append("| " + " | ".join(cells) + " |")
                if len(first["rows"]) > 20:
                    output.append(f"| ... | " * (len(fieldnames) - 1) + "... |")
                output.append("")
        
        question_id = search_result.get("questionId", "")
        if question_id:
            output.append(f"*查询ID: {question_id}*")
        
        return "\n".join(output)
    
    @staticmethod
    def write_output_files(
        query_text: str,
        output_dir: Path,
        tables: List[Dict[str, Any]],
        total_rows: int,
        condition_parts: List[str],
    ) -> Tuple[Path, Path]:
        """Write output Excel (multiple sheets) and description"""
        safe_name = safe_filename(query_text)
        file_path = output_dir / f"mx_data_{safe_name}.xlsx"
        desc_path = output_dir / f"mx_data_{safe_name}_description.txt"
        
        # Write all tables to a single Excel file with multiple sheets
        write_xlsx(file_path, tables)
        
        # Write description file
        description_lines = [
            "金融数据查询结果说明",
            "=" * 40,
            f"查询内容: {query_text}",
            f"数据文件路径: {file_path}",
            f"描述文件路径: {desc_path}",
            f"数据行数: {total_rows}",
            f"表数量: {len(tables)}",
            f"Sheet 列表: {', '.join([t['sheet_name'] for t in tables])}",
        ]
        if condition_parts:
            description_lines.append("")
            description_lines.append("筛选条件:")
            description_lines.extend(condition_parts)
        
        desc_path.write_text("\n".join(description_lines), encoding="utf-8")
        return file_path, desc_path

def main():
    """命令行入口 - 保持与 MX_FinData 一致的使用方式，输出 Excel 多 sheet"""
    if len(sys.argv) < 2:
        print(f"用法: {sys.argv[0]} \"查询问句\" [输出目录]")
        print("默认输出目录:", Path(__file__).resolve().parents[3] / ".local" / "mx" / "mx-data")
        print("示例: python mx_data.py \"同花顺最近3年每天的最新价\"")
        sys.exit(1)
    
    # Build query
    if len(sys.argv) >= 3:
        query = " ".join(sys.argv[1:-1])
        output_dir = Path(sys.argv[-1])
    else:
        query = " ".join(sys.argv[1:])
        output_dir = Path(__file__).resolve().parents[3] / ".local" / "mx" / "mx-data"
    
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        mx = MXData()
        result = mx.query(query)
        tables, condition_parts, total_rows, err = mx.parse_result(result)
        
        if err:
            print(f"错误: {err}")
            sys.exit(1)
        
        # Terminal preview
        print(mx.format_terminal(result, tables, total_rows))
        
        # Write Excel (multiple sheets) + description txt
        file_path, desc_path = mx.write_output_files(query, output_dir, tables, total_rows, condition_parts)
        print(f"\nExcel 文件: {file_path}")
        print(f"描述文件: {desc_path}")
        print(f"总行数: {total_rows}, 表数: {len(tables)}")
        
        # Save original JSON
        json_filename = output_dir / f"mx_data_{safe_filename(query)}_raw.json"
        with open(json_filename, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"原始JSON: {json_filename}")
            
    except Exception as e:
        print(f"错误: {str(e)}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
