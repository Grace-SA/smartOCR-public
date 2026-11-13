"""Recover explicitly printed accounting columns, never sum product rows."""
from html.parser import HTMLParser
import re


class AccountingTables(HTMLParser):
    def __init__(self):
        super().__init__(); self.tables=[]; self.rows=None; self.row=None; self.cell=None

    def handle_starttag(self, tag, attrs):
        if tag=='table': self.rows=[]
        elif tag=='tr' and self.rows is not None: self.row=[]
        elif tag in ('td','th') and self.row is not None:
            attrs=dict(attrs)
            try: spans=[int(attrs.get(k,1)) for k in ('rowspan','colspan')]
            except (ValueError,TypeError): spans=[1,1]
            self.cell=['',*[min(30,max(1,s)) for s in spans]]

    def handle_data(self,data):
        if self.cell is not None: self.cell[0]+=data

    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(self.cell); self.cell=None
        elif tag=='tr' and self.row is not None:
            self.rows.append(self.row); self.row=None
        elif tag=='table' and self.rows is not None:
            self.tables.append(self.rows); self.rows=None


def accounting_column_lines(text):
    parser=AccountingTables(); parser.feed(text)
    output=[]
    label=re.compile(r'(?:grand\s+|invoice\s+)?total(?:\s+(?:incl(?:uding)?\.?|inc\.?|ex(?:clud(?:es|ing))?\.?)\s+(?:gst|tax))?',re.I)
    amount=re.compile(r'(?:AUD\s*)?\$?\s*-?\d[\d,]*[.]\d{2}',re.I)
    date_label=re.compile(r'(?:(?:invoice|transaction|purchase)\s+)?date\s*:?',re.I)
    date_value=re.compile(r'\d{1,4}[-/.]\d{1,2}[-/.]\d{2,4}')
    for table in parser.tables:
        grid={}
        for y,row in enumerate(table):
            x=0
            for value,height,width in row:
                while (y,x) in grid: x+=1
                for dy in range(height):
                    for dx in range(width): grid[y+dy,x+dx]=value.strip()
                x+=width
        for (y,x),value in grid.items():
            # Only a dedicated summary header followed by one numeric cell.
            # Product tables with a Total column are not invoice summaries.
            row_values=[v for (yy,_),v in grid.items() if yy==y]
            if any(re.search(r'\b(?:description|product|quantity|qty|unit\s*price|code)\b',v,re.I) for v in row_values): continue
            below=grid.get((y+1,x),'')
            if label.fullmatch(value) and amount.fullmatch(below):
                output.append(value+': '+below)
            elif date_label.fullmatch(value) and date_value.fullmatch(below):
                output.append(value.rstrip(':')+': '+below)
    return list(dict.fromkeys(output))
