"""Interface Streamlit local para acompanhar o tráfego aéreo e seus alertas."""

import sqlite3
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pydeck as pdk
import streamlit as st

from aeromonitor.config import AIRPORTS, Settings
from aeromonitor.control import apply_selection, select_region, selected_region
from aeromonitor.dashboard_data import collection_health, snapshot

LABELS = {
    "proximity": "Proximidade",
    "low_altitude": "Baixa altitude",
    "vertical_movement": "Movimento vertical",
    "possible_approach": "Possível aproximação",
}


def local_time(timestamp: int | None) -> str:
    """Formate segundos Unix no fuso de São Paulo, incluindo a data."""
    if timestamp is None:
        return "—"
    return (
        datetime.fromtimestamp(timestamp, UTC)
        .astimezone(ZoneInfo("America/Sao_Paulo"))
        .strftime("%d/%m %H:%M:%S")
    )


def render_map(positions: list[dict], alerts: list[dict], region, now: int):
    """Mostre posições com tooltip e destaque aproximações dos últimos cinco minutos."""
    approaching = {
        a["icao24"]
        for a in alerts
        if a["kind"] == "possible_approach" and now - a["observed_at"] <= 300
    }
    points = [
        {
            **p,
            "label": p["callsign"] or p["icao24"],
            "altitude": f"{p['altitude_m']:.0f} m"
            if p["altitude_m"] is not None
            else "Não informada",
            "speed": f"{p['velocity_ms'] * 3.6:.0f} km/h"
            if p["velocity_ms"] is not None
            else "Não informada",
            "updated": local_time(p["observed_at"]),
            "color": [245, 158, 11] if p["icao24"] in approaching else [14, 165, 233],
        }
        for p in positions
    ]
    center = [{"longitude": region.longitude, "latitude": region.latitude}]
    layers = [
        pdk.Layer(
            "ScatterplotLayer",
            center,
            get_position="[longitude, latitude]",
            get_radius=region.radius_km * 1000,
            stroked=True,
            filled=False,
            get_line_color=[100, 116, 139],
            line_width_min_pixels=1,
        ),
        pdk.Layer(
            "ScatterplotLayer",
            center,
            get_position="[longitude, latitude]",
            get_fill_color=[100, 116, 139],
            get_radius=200,
            radius_min_pixels=5,
        ),
        pdk.Layer(
            "ScatterplotLayer",
            points,
            get_position="[longitude, latitude]",
            get_fill_color="color",
            get_radius=300,
            radius_min_pixels=7,
            pickable=True,
        ),
    ]
    st.pydeck_chart(
        pdk.Deck(
            map_provider="carto",
            map_style="light",
            layers=layers,
            initial_view_state=pdk.ViewState(
                latitude=region.latitude, longitude=region.longitude, zoom=9
            ),
            tooltip={
                "text": "{label}\nAltitude: {altitude}\nVelocidade: {speed}\nAtualização: {updated}"
            },
        ),
        height=440,
    )
    st.caption(
        "Azul: posição recente · Laranja: possível aproximação recente · Cinza: centro e raio"
    )


def main():
    """Configure controles e atualize os dados a cada cinco segundos sem coletar da API."""
    st.set_page_config(page_title="AeroMonitor", page_icon="✈️", layout="wide")
    cfg = Settings()
    default_region = cfg.region
    try:
        apply_selection(cfg, default_region)
    except (sqlite3.Error, ValueError):
        st.error("Não foi possível ler a cidade selecionada. Verifique o banco de controle.")
        return
    region = cfg.monitored_region()
    st.title("AeroMonitor")
    st.caption(f"{region.name} · Raio de {region.radius_km:g} km · Fonte: OpenSky Network")
    with st.sidebar:
        st.header("Visualização")
        options = list(AIRPORTS)
        names = {key: value[0] for key, value in AIRPORTS.items()}
        if default_region == "custom" or cfg.region == "custom":
            options.append("custom")
            names["custom"] = cfg.custom_name
        with st.form("region_selection"):
            choice = st.selectbox(
                "Cidade / aeroporto",
                options,
                index=options.index(cfg.region),
                format_func=names.get,
            )
            if st.form_submit_button("Monitorar cidade"):
                try:
                    select_region(cfg.control_database_path, choice)
                except (sqlite3.Error, ValueError):
                    st.error("Não foi possível salvar a cidade. Tente novamente.")
                else:
                    st.rerun()
        hours = st.selectbox(
            "Período dos alertas", [1, 6, 24], format_func=lambda h: f"Últimas {h} h"
        )
        search = st.text_input("Buscar aeronave", placeholder="Callsign ou ICAO24").strip().lower()
        selected = st.multiselect("Tipos de alerta", list(LABELS), format_func=LABELS.get)
        st.caption(
            "A cidade selecionada vale para todos os usuários. A coleta muda no próximo ciclo, "
            "respeitando o intervalo e os limites da API."
        )
        st.caption("Horários em America/Sao_Paulo. Mapa-base requer internet.")

    @st.fragment(run_every=5)
    def live():
        """Leia um snapshot e desenhe indicadores, mapa e tabelas filtradas."""
        now = int(time.time())
        try:
            if selected_region(cfg.control_database_path, default_region) != cfg.region:
                st.rerun()
        except (sqlite3.Error, ValueError):
            st.error("Não foi possível verificar a cidade selecionada.")
            return
        try:
            data = snapshot(cfg.database_path, region.id, now, cfg.max_position_age_seconds, hours)
        except sqlite3.Error:
            st.error(
                "Não foi possível ler os dados do painel. Verifique o consumidor de visualização."
            )
            return
        level, message = collection_health(data["collection"], now)
        st.caption(
            "Cidade selecionada: "
            + region.name
            + ". A última coleta OK abaixo confirma quando houve dados desta região."
        )
        getattr(st, level)(message)
        positions = [
            p
            for p in data["positions"]
            if search in (p["callsign"] or "").lower() or search in p["icao24"].lower()
        ]
        alerts = [
            a
            for a in data["alerts"]
            if (not selected or a["kind"] in selected)
            and (search in (a["callsign"] or "").lower() or search in a["icao24"].lower())
        ]
        cols = st.columns(4)
        cols[0].metric(
            "Região", cfg.region.capitalize() if cfg.region != "custom" else cfg.custom_name
        )
        cols[1].metric("Aeronaves recentes", len(positions))
        cols[2].metric("Alertas no filtro", len(alerts))
        cols[3].metric("Última coleta OK", local_time(data["last_success_at"]))
        st.subheader("Tráfego na região")
        render_map(positions, data["alerts"], region, now)
        if not positions:
            st.info(
                "Nenhuma posição recente para este filtro. "
                "Posições antigas saem do mapa automaticamente."
            )
        with st.expander("Posições e detalhes"):
            st.dataframe(
                [
                    {
                        "Aeronave": p["callsign"] or p["icao24"],
                        "ICAO24": p["icao24"],
                        "Altitude (m)": p["altitude_m"],
                        "Velocidade (m/s)": p["velocity_ms"],
                        "Distância (km)": round(p["distance_km"], 1),
                        "Em solo": p["on_ground"],
                        "Atualização": local_time(p["observed_at"]),
                    }
                    for p in positions
                ],
                hide_index=True,
            )
        st.subheader("Eventos detectados")
        if alerts:
            st.dataframe(
                [
                    {
                        "Horário": local_time(a["observed_at"]),
                        "Aeronave": a["callsign"] or a["icao24"],
                        "Evento": LABELS.get(a["kind"], a["kind"]),
                        "Informação": a["message"],
                    }
                    for a in alerts
                ],
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("Nenhum alerta no período e nos filtros selecionados.")
        st.caption(
            f"Painel atualizado às {local_time(now)} · Até 1.000 alertas por período · "
            "Altitude barométrica não representa altura sobre o terreno."
        )

    live()


if __name__ == "__main__":
    main()
