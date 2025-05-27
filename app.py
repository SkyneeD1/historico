import streamlit as st
import fitz  # PyMuPDF
import camelot
import tempfile
import pandas as pd
import os
import re

st.set_page_config(page_title="Extrator de Histórico Salarial", layout="wide")
st.title("📑 Extrator de Histórico Salarial - Daniel Tominaga")

uploaded_file = st.file_uploader("📤 Envie o PDF do processo", type=["pdf"])
paginas_input = st.text_input("📄 Quais páginas deseja extrair? (Ex.: 220-225 ou 490)")

if uploaded_file and paginas_input:
    if st.button("🚀 Processar"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.read())
            caminho_pdf = tmp_file.name

        try:
            # 🔢 Processar entrada de páginas
            paginas = []
            for intervalo in paginas_input.split(","):
                partes = intervalo.strip().split("-")
                if len(partes) == 2:
                    start, end = int(partes[0]), int(partes[1])
                    paginas.extend(list(range(start, end + 1)))
                elif len(partes) == 1:
                    paginas.append(int(partes[0]))

            progresso = st.progress(0, text="Iniciando extração...")

            dfs_finais = []

            for idx, pag in enumerate(paginas):
                progresso.progress((idx + 1) / len(paginas), text=f"Extraindo página {pag}...")

                tabelas = camelot.read_pdf(caminho_pdf, pages=str(pag), flavor='stream')

                if len(tabelas) == 0:
                    st.warning(f"Aviso 🚨: Nenhuma tabela encontrada na página {pag}.")
                    continue

                for t in tabelas:
                    df_temp = t.df.reset_index(drop=True)

                    # Detectar linha de cabeçalho
                    linha_cabecalho = None
                    for i, row in df_temp.iterrows():
                        if any(isinstance(c, str) and re.match(r'^[A-Z]{3}/\d{4}$', c.strip()) for c in row.values):
                            linha_cabecalho = i
                            break

                    if linha_cabecalho is None:
                        continue  # Pula se não encontrou cabeçalho

                    df_temp.columns = df_temp.iloc[linha_cabecalho]
                    df_temp = df_temp.drop(index=list(range(0, linha_cabecalho + 1))).reset_index(drop=True)

                    dfs_finais.append(df_temp)

            progresso.empty()

            if not dfs_finais:
                st.error("❌ Nenhuma tabela válida encontrada nas páginas.")
                st.stop()

            df = pd.concat(dfs_finais).reset_index(drop=True)

            # 🔥 Limpeza
            df = df.drop(columns=[col for col in df.columns if 'TOTAL' in str(col) or 'MÉDIA' in str(col)], errors='ignore')
            df = df[~df.iloc[:, 0].astype(str).str.contains("TOTAL|MÉDIA|BANCO|CONTA|AGÊNCIA|DADOS", regex=True, na=False)]

            verba_coluna = df.columns[0]

            # 🔥 Filtro inteligente
            padrao_manter = r'SALARIO|HORAS EXTRAS|ADIC|NOTURNO|PERICUL|INSALUBR|DSR|SOBREAVISO|PRODUTIVID'
            padrao_remover = r'FER|RESC|API|VENC|SALDO|ADIANT|ABONO|MEDIA|DIF|13'

            df_filtrado = df[df[verba_coluna].astype(str).str.contains(padrao_manter, flags=re.IGNORECASE, regex=True, na=False)]
            df_filtrado = df_filtrado[~df_filtrado[verba_coluna].astype(str).str.contains(padrao_remover, flags=re.IGNORECASE, regex=True, na=False)]

            # 🔄 Pivotar
            df_meltado = df_filtrado.melt(id_vars=[verba_coluna], var_name='MÊS', value_name='VALOR')

            df_pivot = df_meltado.pivot_table(
                index='MÊS',
                columns=verba_coluna,
                values='VALOR',
                aggfunc='first'
            ).reset_index()

            # ➕ Corrigir meses agrupados (Ex.: ABR/2019\nMAIO/2019)
            df_pivot['MÊS'] = df_pivot['MÊS'].astype(str)

            linhas_explodir = df_pivot[df_pivot['MÊS'].str.contains('\n')]
            if not linhas_explodir.empty:
                novas_linhas = []
                for _, row in linhas_explodir.iterrows():
                    meses = row['MÊS'].split("\n")
                    for mes in meses:
                        nova = row.copy()
                        nova['MÊS'] = mes.strip()
                        novas_linhas.append(nova)

                df_expandido = pd.DataFrame(novas_linhas)
                df_pivot = pd.concat([
                    df_pivot[~df_pivot['MÊS'].str.contains('\n')],
                    df_expandido
                ], ignore_index=True)

            # 🔢 Ordenar os meses
            ordem_meses = {
                'JAN': 1, 'FEV': 2, 'MAR': 3, 'ABR': 4, 'MAIO': 5, 'JUN': 6,
                'JUL': 7, 'AGO': 8, 'SET': 9, 'OUT': 10, 'NOV': 11, 'DEZ': 12
            }

            def ordenar_data(data):
                try:
                    mes, ano = data.split('/')
                    return int(ano) * 100 + ordem_meses.get(mes.upper(), 0)
                except:
                    return 999999

            df_pivot['ordem'] = df_pivot['MÊS'].apply(ordenar_data)
            df_pivot = df_pivot.sort_values('ordem').drop(columns=['ordem']).reset_index(drop=True)

            # ✅ Mostrar
            st.subheader("🔍 Tabela Organizada e Filtrada")
            st.dataframe(df_pivot)

            # 📥 Download CSV
            csv = df_pivot.to_csv(index=False, sep=';', encoding='utf-8-sig').encode('utf-8-sig')

            st.download_button(
                label="📥 Baixar CSV Organizado",
                data=csv,
                file_name="historico_organizado.csv",
                mime='text/csv'
            )

        except Exception as e:
            st.error(f"❌ Erro: {e}")
