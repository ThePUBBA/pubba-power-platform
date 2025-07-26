with zipfile.ZipFile(io_module.BytesIO(response.content)) as zf:
    print("ZIP contents:", zf.namelist())  # 👈 Add this debug line
    csv_file = [f for f in zf.namelist() if f.endswith('.csv')][0]
    with zf.open(csv_file) as f:
        df = pd.read_csv(f)

