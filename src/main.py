# src/main.py

# Data
import pandas as pd
import numpy as np

# Dato og tid
from datetime import datetime, timedelta

# Spark / Databricks
from pyspark.sql import functions as F
from pyspark.sql import types as T
from pyspark.sql.window import Window

# Visualisering
import matplotlib.pyplot as plt
import seaborn as sns

# Filbaner
from pathlib import Path

# Logging
import logging

# PDF-tolkning
import fitz  # PyMuPDF


from extraction.pdf_parser import extract_text


def main():
    text = extract_text("data/raw/sample.pdf")

    print(text[:1000])


if __name__ == "__main__":
    main()
    
    

