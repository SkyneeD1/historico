import streamlit as st
import fitz  # PyMuPDF
import camelot
import pandas as pd
import re
import tempfile
import numpy as np

st.set_page_config(page_title="📑 Extrator de Histórico Salarial", layout="wide")
st.title("📑 Extrator de Histórico Salarial - Daniel Tominaga")

# 🔥 Campo para nome do arquivo
nome_arquivo = st.text_input("📄 Nome do Arquivo (sem extensão):", value="")
nome_arquivo_final = f"HS - {nome_arquivo}"

# 🔥 Seleção do tipo de extração
tipo_extracao = st.selectbox(
    "Selecione o tipo de histórico salarial:",
    ["Vtal (Tabela)"]
)

uploaded_file = st.file_uploader("📤 Envie o PDF da ficha financeira", type=["pdf"])

MES_ANO_REGEX = re.compile(r"^[A-Z]{3}/\d{4}$")


def collapse_duplicate_columns_keep_first_nonempty(df: pd.DataFrame) -> pd.DataFrame:
    """
    Se houver colunas duplicadas (ex.: 'JAN/2020' 2x),
    colapsa em uma só pegando o primeiro valor não vazio por linha.
    """
    cols = list(df.columns)
    unique_order = []
    seen = set()

    for c in cols:
        if c not in seen:
            unique_order.append(c)
            seen.add(c)

    out = pd.DataFrame(index=df.index)

    for c in unique_order:
        same_cols = [cc for cc in cols if cc == c]
        if len(same_cols) == 1:
            out[c] = df[c]
        else:
            block = df[same_cols].copy()
            block = block.replace(r"^\s*$", np.nan, regex=True)
            out[c] = block.bfill(axis=1).iloc[:, 0]

    return out


def normalizar_tabela(df_in: pd.DataFrame) -> pd.DataFrame:
    """
    - trim nos nomes de colunas
    - 1ª coluna vira VERBA
    - remove colunas vazias
    - colapsa colunas duplicadas (meses duplicados)
    """
    df = df_in.copy()

    # normaliza nomes das colunas
    cols = []
    for c in df.columns:
        cols.append("" if c is None else str(c).strip())

    if cols:
        cols[0] = "VERBA"
    df.columns = cols

    # remove colunas com nome vazio
    df = df.loc[:, df.columns.astype(str).str.strip() != ""]

    # colapsa duplicadas (principalmente meses duplicados)
    df = collapse_duplicate_columns_keep_first_nonempty(df)

    # garante VERBA na frente
    if "VERBA" in df.columns:
        cols = ["VERBA"] + [c for c in df.columns if c != "VERBA"]
        df = df[cols]

    return df


def limpar_codigo_verba(serie: pd.Series) -> pd.Series:
    """
    Remove códigos tipo:
    0005- SALARIO BASE
    00030-ADIC NOTURNO
    00045 - DSR ...
    e também 0825 HORAS...
    (somente quando começa com pelo menos 3 dígitos/zeros para não afetar "13º")
    """
    s = serie.astype(str)

    # remove "0005-" / "0005 - " / "0005–" etc
    s = s.str.replace(r"^\s*0*\d{3,}\s*[-–—]\s*", "", regex=True)

    # remove "0825 " (código + espaço)
    s = s.str.replace(r"^\s*0*\d{3,}\s+", "", regex=True)

    return s.str.strip()


if tipo_extracao != "Selecione..." and uploaded_file:
    if st.button("🚀 Processar"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.read())
            caminho_pdf = tmp_file.name

        doc = fitz.open(caminho_pdf)
        total_paginas = doc.page_count
        st.write(f"Total de páginas no PDF: {total_paginas}")

        # ✅ Seleção de páginas
        col1, col2 = st.columns(2)
        with col1:
            pagina_inicial = st.number_input("📌 Página inicial", min_value=1, max_value=total_paginas, value=1, step=1)
        with col2:
            pagina_final = st.number_input("📌 Página final", min_value=1, max_value=total_paginas, value=total_paginas, step=1)

        if pagina_final < pagina_inicial:
            st.error("❌ Página final não pode ser menor que a inicial.")
            st.stop()

        paginas = list(range(int(pagina_inicial), int(pagina_final) + 1))
        st.write(f"Páginas selecionadas: {paginas} (Total: {len(paginas)})")

        progresso = st.progress(0, text="Iniciando extração...")

        try:
            dfs_finais = []

            for idx, pag in enumerate(paginas):
                progresso.progress((idx + 1) / len(paginas), text=f"Processando página {pag}...")

                tabelas = camelot.read_pdf(caminho_pdf, pages=str(pag), flavor="stream")

                if len(tabelas) == 0:
                    st.warning(f"Aviso 🚨: Nenhuma tabela encontrada na página {pag}.")
                    continue

                for t in tabelas:
                    df_temp = t.df.reset_index(drop=True)

                    # acha a linha onde aparecem colunas tipo "JAN/2020"
                    linha_cabecalho = None
                    for i, row in df_temp.iterrows():
                        if any(isinstance(c, str) and MES_ANO_REGEX.match(c.strip()) for c in row.values):
                            linha_cabecalho = i
                            break

                    if linha_cabecalho is None:
                        continue

                    df_temp.columns = df_temp.iloc[linha_cabecalho]
                    df_temp = df_temp.drop(index=list(range(0, linha_cabecalho + 1))).reset_index(drop=True)

                    df_temp = normalizar_tabela(df_temp)

                    # só mantém meses + VERBA
                    cols_validas = ["VERBA"] + [c for c in df_temp.columns if MES_ANO_REGEX.match(str(c).strip())]
                    cols_validas = [c for c in cols_validas if c in df_temp.columns]
                    df_temp = df_temp[cols_validas]

                    dfs_finais.append(df_temp)

            progresso.empty()

            if not dfs_finais:
                st.error("❌ Nenhuma tabela válida encontrada nas páginas selecionadas.")
                st.stop()

            df = pd.concat(dfs_finais, ignore_index=True)
            df = normalizar_tabela(df)

            # ✅ remove códigos antes do nome da verba
            df["VERBA"] = limpar_codigo_verba(df["VERBA"])

            # remove colunas TOTAL/MÉDIA se virarem colunas
            df = df.drop(columns=[c for c in df.columns if "TOTAL" in str(c).upper() or "MÉDIA" in str(c).upper()], errors="ignore")

            # remove linhas ruins
            df = df[~df["VERBA"].astype(str).str.contains("TOTAL|MÉDIA|BANCO|CONTA|AGÊNCIA|DADOS", regex=True, na=False)]

            # 🔥 Filtro inteligente
            padrao_manter = r"SALARIO|HORAS EXTRAS|ADIC|NOTURNO|PERICUL|INSALUBR|DSR|BANCO|SOBREAVISO|PRODUTIVID"
            padrao_remover = r"FER|RESC|API|VENC|SALDO|ADIANT|ABONO|MEDIA|DIF|13"

            df_filtrado = df[df["VERBA"].astype(str).str.contains(padrao_manter, flags=re.IGNORECASE, regex=True, na=False)]
            df_filtrado = df_filtrado[~df_filtrado["VERBA"].astype(str).str.contains(padrao_remover, flags=re.IGNORECASE, regex=True, na=False)]

            # Melt seguro: só meses como value_vars
            value_vars = [c for c in df_filtrado.columns if c != "VERBA" and MES_ANO_REGEX.match(str(c).strip())]

            if not value_vars:
                st.error("❌ Não encontrei colunas de mês/ano (ex.: JAN/2020) após o filtro.")
                st.stop()

            df_meltado = df_filtrado.melt(
                id_vars=["VERBA"],
                value_vars=value_vars,
                var_name="MÊS",
                value_name="VALOR"
            )

            df_pivot = df_meltado.pivot_table(
                index="MÊS",
                columns="VERBA",
                values="VALOR",
                aggfunc="first"
            ).reset_index()

            # 🔢 Ordenar os meses
            ordem_meses = {"JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "MAIO": 5, "JUN": 6,
                           "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12}

            def ordenar_data(data):
                try:
                    data = str(data).strip()
                    mes, ano = data.split("/")
                    return int(ano) * 100 + ordem_meses.get(mes.upper(), 0)
                except:
                    return 999999

            df_pivot["ordem"] = df_pivot["MÊS"].apply(ordenar_data)
            df_pivot = df_pivot.sort_values("ordem").drop(columns=["ordem"]).reset_index(drop=True)

            st.subheader("🔍 Tabela Organizada e Filtrada")
            st.dataframe(df_pivot)

            csv = df_pivot.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")
            st.download_button(
                label="📥 Baixar CSV Organizado",
                data=csv,
                file_name=f"{nome_arquivo_final}.csv",
                mime="text/csv"
            )

        except Exception as e:
            st.error(f"❌ Erro: {e}")
            try:
                st.write("🔎 Debug rápido:")
                if "df" in locals():
                    dup_cols = df.columns[df.columns.duplicated()].tolist()
                    st.write("Colunas duplicadas no DF final:", dup_cols)
                    st.write("Colunas finais:", list(df.columns)[:40])
            except:
                pass
