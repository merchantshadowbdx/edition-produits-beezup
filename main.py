import requests
import streamlit as st
import pandas as pd
import re
import io
from xlsxwriter import Workbook


def get_headers(token):
    return {
        "Content-Type": "application/json",
        "Ocp-Apim-Subscription-Key": token
    }


def get_attributes(catalog_id, token):
    url = f"https://api.beezup.com/v2/user/channelCatalogs/{catalog_id}"
    response = requests.get(url, headers=get_headers(token)).json()
    column_mappings = response.get("columnMappings", [])
    data = []
    for column in column_mappings:
        channel_column_id = column.get("channelColumnId")
        channel_column_name = column.get("channelColumnName")
        data.append({
            "Channel Column Name": channel_column_name,
            "Channel Column Id": channel_column_id,
        })
    df = pd.DataFrame(data)
    return df


def get_skus_data(skus, catalog_id, token):
    url = f"https://api.beezup.com/v2/user/channelCatalogs/{catalog_id}/products"
    data = []
    page_number = 1

    while True:
        payload = {
            "pageNumber": page_number,
            "pageSize": 1000,
            "criteria": {
                "logic": "cumulative",
                "exist": True,
                "uncategorized": False,
                "excluded": False,
                "disabled": False
            },
            "productFilters": {
                "catalogSkus": skus # Filtre sur la liste de skus à traiter
            }
        }

        response = requests.post(url, headers=get_headers(token), json=payload).json()
        pagination_result = response.get("paginationResult", {})
        page_count = pagination_result.get("pageCount")
        product_infos = response.get("productInfos", [])

        for product in product_infos:
            product_id = product.get("productId", None)
            product_sku = product.get("productSku", None)
            overrides = product.get("overrides", {})

            data_raw = {
                "Product Id": product_id,
                "Product Sku": product_sku,
                "Catalog Id": catalog_id
            }

            # Extraction des attributs déjà édités
            for key, value in overrides.items():
                column_id = key
                edition = value.get("override", None)
                data_raw[column_id] = edition

            data.append(data_raw)

        if page_number >= page_count:
            break
        page_number += 1

    df = pd.DataFrame(data)
    return df


def id_to_name(df_base, df_attributes, selected_attr):
    df_attributes_clean = df_attributes.drop_duplicates(subset="Channel Column Id")

    # Création du dictionnaire {column_id: column_name}
    id_to_name_mapping = dict(zip(
        df_attributes_clean["Channel Column Id"],
        df_attributes_clean["Channel Column Name"]
    ))

    # Ajouter les colonnes manquantes issues de selected_attr
    for attr_name in selected_attr:
        matching_ids = df_attributes_clean[df_attributes_clean["Channel Column Name"] == attr_name]["Channel Column Id"]
        for column_id in matching_ids:
            if column_id not in df_base.columns:
                df_base[column_id] = None

    # Création du mapping complet pour tous les column_ids
    full_renaming = {
        column_id: f"{name} | {column_id}"
        for column_id, name in id_to_name_mapping.items()
        if column_id in df_base.columns
    }

    # Copier et renommer le DataFrame
    df_temp = df_base.copy()
    df= df_temp.rename(columns=full_renaming)
    return df


def name_to_id(df_template_filled):
    # Fonction pour extraire l'ID à partir du nom concaténé
    def extract_id(col):
        match = re.search(r"\|\s*(.+)$", col)
        return match.group(1) if match else col

    # Création d’un mapping {nom complet -> column_id}
    mapping = {col: extract_id(col) for col in df_template_filled.columns}

    # Renommage du DataFrame
    df = df_template_filled.rename(columns=mapping)
    return df


def edit_attributes(catalog_id, product_id, payload, token):
    url = f"https://api.beezup.com/v2/user/channelCatalogs/{catalog_id}/products/{product_id}/overrides"
    response = requests.put(url, headers=get_headers(token), json=payload)
    status = response.status_code
    if status == 204:
        return True
    else:
        return False


def main():
    # Configuration de la page et du titre de l'onglet
    st.set_page_config(page_title="Edition Multi-Attributs", layout="wide")

    # Disposition en deux onglets
    tab1, tab2 = st.tabs(["EDITION PRODUITS", "SUPPRESSION EDITIONS"])

    # --- Onglet 1 : édition ---
    with tab1:
        st.title("EDITION PRODUITS BEEZUP MULTI-ATTRIBUTS")
        st.markdown("<br>", unsafe_allow_html=True)

        # Initialisation de session_state pour suivre la progression
        if "token" not in st.session_state:  # Token
            st.session_state["token"] = None
        if "catalog" not in st.session_state:  # Catalog_id
            st.session_state["catalog"] = None
        if "df_attributes" not in st.session_state:  # DataFrame attributs
            st.session_state["df_attributes"] = None
        if "selected_attr" not in st.session_state:  # Attributs à éditer
            st.session_state["selected_attr"] = []
        if "df_renamed" not in st.session_state:  # DataFrame avec les colonnes renommées
            st.session_state["df_renamed"] = None
        if "df_restored" not in st.session_state:  # Template
            st.session_state["df_restored"] = None

        # Disposition en deux colonnes
        col1, col2 = st.columns(2)

        # --- Colonne 1 : Actions 1 & 2 ---
        with col1:
            with st.container(border=True):
                st.subheader("\u2776 PARAMÈTRES")
                bzp_token = st.text_input("*Token Primaire*", type="password")
                catalog_id = st.text_input("*Channel Catalog Id*")

                if st.button("Valider les paramètres", key="parameters"):
                    if bzp_token and catalog_id:
                        st.session_state["token"] = bzp_token
                        st.session_state["catalog"] = catalog_id
                        st.session_state["df_attributes"] = get_attributes(catalog_id, bzp_token)  # Stockage de la liste des attributs

            with st.container(border=True):
                st.subheader("\u2777 CHOIX DES ATTRIBUTS")
                df_attributes = st.session_state["df_attributes"]

                if df_attributes is not None and not df_attributes.empty:
                    attr_names = df_attributes["Channel Column Name"].tolist()  # Extraction des noms d'attributs
                    selected_attr = st.multiselect("*Attributs disponibles*", attr_names)  # Stockage des attributs choisis
                    if selected_attr:
                        st.session_state["selected_attr"] = selected_attr
                else:
                    st.info("Veuillez renseigner les paramètres avant de sélectionner les attributs.")

        # --- Colonne 2 : Actions 3 & 4 ---
        with col2:
            with st.container(border=True):
                st.subheader("\u2778 IMPORTATION DES SKUS À TRAITER")
                skus_list = st.text_area("*Collez la liste des SKUs à éditer (un par ligne)*")

                # Si la zone est vide, on efface le DataFrame
                if not skus_list.strip():
                    st.session_state["df_renamed"] = None

                if st.button("Valider la sélection"):
                    if skus_list and st.session_state.get("selected_attr"):
                        skus = [sku.strip() for sku in skus_list.split("\n") if sku.strip()]  # Stocker les skus
                        df_base = get_skus_data(skus, catalog_id, bzp_token)  # Extraire les données
                        df_renamed = id_to_name(
                            df_base,
                            st.session_state["df_attributes"],
                            st.session_state["selected_attr"]
                        )  # Renommer les colonnes
                        st.session_state["df_renamed"] = df_renamed
                    elif not bzp_token or not catalog_id:
                        st.warning("Veuillez renseigner votre Token Primaire et/ou le Channel Catalog Id de la boutique.")
                    elif not selected_attr:
                        st.warning("Veuillez sélectionner au moins un attribut.")
                    else:
                        st.warning("Veuillez entrer des SKUs.")

            with st.container(border=True):
                st.subheader("\u2779 IMPORTATION DU TEMPLATE")
                template = st.file_uploader("*Importez le template complété*", type=["xlsx"])

                # Si aucun fichier n'est présent, on efface le DataFrame
                if not template:
                    st.session_state["df_restored"] = None

                if template:
                    df_template = pd.read_excel(template)
                    df_restored = name_to_id(df_template)
                    st.session_state["df_restored"] = df_restored

        # --- Affichage dynamique des DataFrames sous les colonnes ---
        st.markdown("<br>", unsafe_allow_html=True)
        df_restored = st.session_state.get("df_restored")
        df_renamed = st.session_state.get("df_renamed")

        # Initialiser l'état du bouton
        if "edit_launched" not in st.session_state:
            st.session_state.edit_launched = False

        if df_restored is not None and not df_restored.empty:
            with st.container(border=True):
                st.subheader("\u277A TEMPLATE PRÊT POUR EDITION")
                # Placeholders dynamiques
                display_placeholder = st.empty()
                progress_placeholder = st.empty()

                # Afficher le DataFrame initial dans le placeholder
                if not st.session_state.edit_launched:
                    display_placeholder.data_editor(df_restored, hide_index=True)

                    # --- Afficher le bouton uniquement si pas encore cliqué ---
                    if st.button("Editer les produits"):
                        st.session_state.edit_launched = True
                        st.rerun()

                # --- Si édition en cours ---
                if st.session_state.edit_launched:
                    # 1. Effacer le DataFrame initial
                    display_placeholder.empty()

                    # 2. Afficher la barre de progression
                    progress_bar = progress_placeholder.progress(0, text="Progression")
                    df_status = df_restored.copy()
                    df_status['Statut'] = ""
                    exclude_cols = ['Product Id', 'Product Sku', 'Catalog Id']
                    column_id_cols = [col for col in df_restored.columns if col not in exclude_cols]

                    total = len(df_restored)
                    for i, (index, row) in enumerate(df_restored.iterrows(), 1):
                        product_id = row["Product Id"]
                        catalog_id = row["Catalog Id"]
                        payload = {}

                        for col in column_id_cols:
                            val = row[col]
                            if pd.notna(val) and val != "None" and val != "":
                                # payload[col] = str(val)
                                payload[col] = f"{val}"

                        try:
                            success = edit_attributes(catalog_id, product_id, payload, bzp_token)
                            if success:
                                df_status.at[index, 'Statut'] = "✅"
                            else:
                                df_status.at[index, 'Statut'] = "❌"
                        except Exception as e:
                            df_status.at[index, 'Statut'] = "⚠️"

                        progress_bar.progress(i / total, text=f"Traitement du produit {i}/{total}")

                    # 3. Effacer la barre de progression
                    progress_placeholder.empty()

                    # 4. Afficher le DataFrame de statut
                    # Réorganiser les colonnes pour que "Statut" soit en premier
                    cols = ["Statut"] + [col for col in df_status.columns if col != "Statut"]
                    df_status = df_status[cols]

                    # Afficher le DataFrame final avec "Statut" en premier
                    display_placeholder.dataframe(df_status, hide_index=True)
                    st.success("Traitement terminé !")
                    st.toast("Tous les produits ont été traités", icon="🎉")

                    # Réinitialisation du session_state
                    for key in ["token", "catalog", "df_attributes", "selected_attr", "df_renamed", "df_restored",
                                "edit_launched"]:
                        if key in st.session_state:
                            del st.session_state[key]

        elif df_renamed is not None and not df_renamed.empty:
            with st.container(border=True):
                st.subheader("TEMPLATE A COMPLETER")
                st.dataframe(df_renamed, hide_index=True)

                # Générer le fichier Excel et le télécharger avec gestion automatique du buffer
                with io.BytesIO() as buffer:
                    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                        df_renamed.to_excel(writer, index=False, sheet_name='Template')
                    buffer.seek(0)  # Revenir au début du buffer avant lecture

                    st.download_button(
                        label="Télécharger le template",
                        data=buffer,
                        file_name="template.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )

    # --- Onglet 2 : suppression ---
    with tab2:
        st.title("SUPPRESSION DES VALEURS EDITEES")
        st.image(image="images/coming_soon.png", width=1000)


if __name__ == "__main__":
    main()
