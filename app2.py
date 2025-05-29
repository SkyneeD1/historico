import streamlit as st
import fitz  # PyMuPDF
import camelot
import pandas as pd
import re
import tempfile


st.set_page_config(page_title="📑 Extrator de Histórico Salarial", layout="wide")
st.title("📑 Extrator de Histórico Salarial - Daniel Tominaga")

# 🔥 Seleção do tipo de extração
tipo_extracao = st.selectbox(
    "Selecione o tipo de histórico salarial:",
    ["Selecione...", "Carreira e Sartorelo (Texto)", "Vtal (Tabela)"]
)

uploaded_file = st.file_uploader("📤 Envie o PDF da ficha financeira", type=["pdf"])
paginas_input = st.text_input("📄 Quais páginas deseja extrair? (Ex.: 252-255 ou 490)")

if tipo_extracao != "Selecione..." and uploaded_file and paginas_input:
    if st.button("🚀 Processar"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.read())
            caminho_pdf = tmp_file.name

        paginas = []
        for intervalo in paginas_input.split(","):
            partes = intervalo.strip().split("-")
            if len(partes) == 2:
                start, end = int(partes[0]), int(partes[1])
                paginas.extend(list(range(start, end + 1)))
            elif len(partes) == 1:
                paginas.append(int(partes[0]))

        progresso = st.progress(0, text="Iniciando extração...")

        # 🔥 OPÇÃO 1 - Carreira e Sartorelo (TEXTO)
        if tipo_extracao == "Carreira e Sartorelo (Texto)":
            registros = []
            doc = fitz.open(caminho_pdf)

            for idx, pag in enumerate(paginas):
                progresso.progress((idx + 1) / len(paginas), text=f"Processando página {pag}...")

                if pag - 1 < len(doc):
                    texto = doc.load_page(pag - 1).get_text("text")
                    linhas = texto.split('\n')

                    indices = [i for i, linha in enumerate(linhas) if re.match(r'^\d{5}-\d{2}', linha)]

                    for idx2, i in enumerate(indices):
                        codigo = linhas[i].strip()
                        limite = indices[idx2 + 1] if idx2 + 1 < len(indices) else len(linhas)
                        bloco = linhas[i + 1:limite]

                        texto_bloco = ' '.join(bloco)

                        tipo_match = re.search(r'\b(V|D)\b', texto_bloco)
                        tipo = tipo_match.group(1) if tipo_match else ''

                        if tipo:
                            partes = texto_bloco.split(f' {tipo} ')
                            descricao = partes[0].strip() if len(partes) >= 1 else ''
                            valores_str = partes[1].strip() if len(partes) >= 2 else ''
                        else:
                            descricao = texto_bloco.strip()
                            valores_str = ''

                        valores = re.findall(r'[\d\.,]+', valores_str)

                        if len(valores) < 13:
                            valores += [''] * (13 - len(valores))
                        elif len(valores) > 13:
                            valores = valores[:13]

                        registro = [pag, codigo, descricao, tipo] + valores
                        registros.append(registro)

            doc.close()
            progresso.empty()

            colunas = ['Pagina', 'Rubrica', 'Descricao', 'Tipo'] + [
                'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez', 'Total'
            ]

            df = pd.DataFrame(registros, columns=colunas)

            # 🔥 Aplicar filtros
            padrao_manter = r'SALARIO|HORAS EXTRAS|FERIADO/FOLGA|VPNI|ADIC|ABONO|NOTURNO|PERICUL|INSALUBR|DSR|SOBREAVISO|PRODUTIVID|QUINQUENIO|ANUENIO|GRATIFICACAO|ACUMULO'
            padrao_remover = r'FER|RESC|API|VENC|SALDO|ADIANT|ABONO|MEDIA|DIF|13'

            df_filtrado = df[df['Descricao'].str.contains(padrao_manter, flags=re.IGNORECASE, na=False)]
            df_filtrado = df_filtrado[~df_filtrado['Descricao'].str.contains(padrao_remover, flags=re.IGNORECASE, na=False)]

            # 🔄 Pivotar
            df_meltado = df_filtrado.melt(id_vars=['Pagina', 'Rubrica', 'Descricao', 'Tipo'],
                                          value_vars=['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'],
                                          var_name='Mes',
                                          value_name='Valor')

            df_pivot = df_meltado.pivot_table(index=['Pagina', 'Mes'],
                                              columns='Descricao',
                                              values='Valor',
                                              aggfunc='first').reset_index()

            ordem_meses = {'Jan':1, 'Fev':2, 'Mar':3, 'Abr':4, 'Mai':5, 'Jun':6,
                           'Jul':7, 'Ago':8, 'Set':9, 'Out':10, 'Nov':11, 'Dez':12}

            df_pivot['Ordem'] = df_pivot['Mes'].map(ordem_meses)
            df_pivot = df_pivot.sort_values(['Pagina', 'Ordem']).drop(columns=['Ordem']).reset_index(drop=True)

            st.subheader("🔍 Tabela Filtrada e Organizada")
            st.dataframe(df_pivot)

            csv = df_pivot.to_csv(index=False, sep=';', encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button(
                label="📥 Baixar CSV Organizado",
                data=csv,
                file_name="historico_organizado.csv",
                mime='text/csv'
            )

        # 🔥 OPÇÃO 2 - VTAL (TABELA)
        elif tipo_extracao == "Vtal (Tabela)":
            try:
                dfs_finais = []

                for idx, pag in enumerate(paginas):
                    progresso.progress((idx + 1) / len(paginas), text=f"Extraindo página {pag}...")

                    tabelas = camelot.read_pdf(caminho_pdf, pages=str(pag), flavor='stream')

                    if len(tabelas) == 0:
                        st.warning(f"Aviso 🚨: Nenhuma tabela encontrada na página {pag}.")
                        continue

                    for t in tabelas:
                        df_temp = t.df.reset_index(drop=True)

                        linha_cabecalho = None
                        for i, row in df_temp.iterrows():
                            if any(isinstance(c, str) and re.match(r'^[A-Z]{3}/\d{4}$', c.strip()) for c in row.values):
                                linha_cabecalho = i
                                break

                        if linha_cabecalho is None:
                            continue

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

                # 🔢 Ordenar os meses
                ordem_meses = {'JAN':1, 'FEV':2, 'MAR':3, 'ABR':4, 'MAIO':5, 'JUN':6,
                               'JUL':7, 'AGO':8, 'SET':9, 'OUT':10, 'NOV':11, 'DEZ':12}

                def ordenar_data(data):
                    try:
                        mes, ano = data.split('/')
                        return int(ano) * 100 + ordem_meses.get(mes.upper(), 0)
                    except:
                        return 999999

                df_pivot['ordem'] = df_pivot['MÊS'].apply(ordenar_data)
                df_pivot = df_pivot.sort_values('ordem').drop(columns=['ordem']).reset_index(drop=True)

                st.subheader("🔍 Tabela Organizada e Filtrada")
                st.dataframe(df_pivot)

                csv = df_pivot.to_csv(index=False, sep=';', encoding='utf-8-sig').encode('utf-8-sig')

                st.download_button(
                    label="📥 Baixar CSV Organizado",
                    data=csv,
                    file_name="historico_organizado.csv",
                    mime='text/csv'
                )

            except Exception as e:
                st.error(f"❌ Erro: {e}")
