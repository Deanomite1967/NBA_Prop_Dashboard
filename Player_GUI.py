import streamlit as st
import pandas as pd
from nba_api.stats.static import players
from nba_api.stats.endpoints import playergamelog, commonplayerinfo, leaguedashteamstats
from datetime import datetime
import altair as alt

@st.cache_data(show_spinner=False)
def get_season_string():
    today = datetime.today()
    if today.month >= 10:  # NBA season starts in October
        start_year = today.year
        end_year = today.year + 1
    else:
        start_year = today.year - 1
        end_year = today.year
    return f"{start_year}-{str(end_year)[-2:]}"


@st.cache_data(show_spinner=False)
def get_player_id(name):
    matches = players.find_players_by_full_name(name)
    return matches[0]["id"] if matches else None

@st.cache_data(show_spinner=False)
def get_player_position(player_id):
    info = commonplayerinfo.CommonPlayerInfo(player_id=player_id).get_data_frames()[0]
    return info.loc[0, "POSITION"]

@st.cache_data(show_spinner=False)
def get_last_10_games(player_id):
    current_season = get_season_string()
    previous_season = f"{int(current_season[:4]) - 1}-{current_season[:2]}"

    logs_current = playergamelog.PlayerGameLog(player_id=player_id, season=current_season).get_data_frames()[0]
    logs_previous = playergamelog.PlayerGameLog(player_id=player_id, season=previous_season).get_data_frames()[0]

    all_logs = pd.concat([logs_current, logs_previous])
    all_logs["GAME_DATE"] = pd.to_datetime(all_logs["GAME_DATE"])
    all_logs = all_logs.sort_values("GAME_DATE", ascending=False)
    return all_logs.head(10)[["GAME_DATE", "MATCHUP", "PTS", "REB", "AST", "MIN"]]

@st.cache_data(show_spinner=False)
def get_dvp_table():
    position_groups = ['G', 'F', 'C']
    dfs = []
    for pos in position_groups:
        stats = leaguedashteamstats.LeagueDashTeamStats(
            measure_type_detailed_defense='Opponent',
            per_mode_detailed='PerGame',
            player_position_abbreviation_nullable=pos,
            season='2024-25'
        )
        df = stats.get_data_frames()[0]
        df['Position'] = pos
        dfs.append(df)
    df_all = pd.concat(dfs)
    df_pivot = df_all.pivot(index='TEAM_NAME', columns='Position', values='OPP_PTS').reset_index()
    df_pivot.columns.name = None
    df_pivot.rename(columns={
        'G': 'Guard Pts Allowed',
        'F': 'Forward Pts Allowed',
        'C': 'Center Pts Allowed'
    }, inplace=True)
    return df_pivot

def matchup_multiplier(pts_allowed, avg, std):
    z = (pts_allowed - avg) / std
    if z >= 1.0:
        return 1.25
    elif z >= 0.5:
        return 1.15
    elif z <= -1.0:
        return 0.85
    elif z <= -0.5:
        return 0.75
    else:
        return 1.00

def get_matchup_score(row, slot, guard_avg, guard_std, forward_avg, forward_std, center_avg, center_std):
    if slot in ['PG', 'SG']:
        return matchup_multiplier(row['Guard Pts Allowed'], guard_avg, guard_std)
    elif slot in ['SF', 'PF']:
        return matchup_multiplier(row['Forward Pts Allowed'], forward_avg, forward_std)
    elif slot == 'C':
        return matchup_multiplier(row['Center Pts Allowed'], center_avg, center_std)
    else:
        return 1.00

def simplify_slot(position):
    if "G" in position:
        return "PG"
    elif "F" in position:
        return "SF"
    elif "C" in position:
        return "C"
    else:
        return "PG"
    
# --- Streamlit UI ---

st.set_page_config(page_title="NBA Player Stats", layout="centered")
st.title("🏀 NBA Player Last 10 Games Stats")

player_name = st.text_input("Enter full player name:", "LeBron James")

team_abbrs = sorted([
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW", "HOU", "IND",
    "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK", "OKC", "ORL", "PHI", "PHX",
    "POR", "SAC", "SAS", "TOR", "UTA", "WAS"
])
opponent_abbr = st.selectbox("Select tonight's opponent:", team_abbrs, index=team_abbrs.index("BOS"))

st.subheader("📈 Set Your Prop Lines")
col1, col2, col3, col4 = st.columns(4)
with col1:
    pts_line = st.number_input("Points line", value=20)
with col2:
    reb_line = st.number_input("Rebounds line", value=5)
with col3:
    ast_line = st.number_input("Assists line", value=5)
with col4:
    min_line = st.number_input("Minutes line", value=30)

def stat_chart(df, stat, line_value):
    df["OverLine"] = df[stat] > line_value
    max_val = df[stat].max()
    y_max = max_val * 1.2

    bars = alt.Chart(df).mark_bar().encode(
        x=alt.X("GAME_DATE:T", title="Game Date"),
        y=alt.Y(stat, title=stat, scale=alt.Scale(domain=[0, y_max])),
        color=alt.condition(
            alt.datum.OverLine,
            alt.value("green"),
            alt.value("red")
        ),
        tooltip=["GAME_DATE", stat]
    )

    line = alt.Chart(pd.DataFrame({stat: [line_value]})).mark_rule(
        color="red", strokeDash=[4, 4]
    ).encode(y=stat)

    labels = alt.Chart(df).mark_text(
        dy=-15,
        color="white",
        fontSize=12
    ).encode(
        x=alt.X("GAME_DATE:T"),
        y=alt.Y(stat),
        text=alt.Text(stat, format=".0f")
    )

    chart = (bars + line + labels).properties(
        height=350,
        title=f"{stat} over Last 10 Games"
    ).configure_axis(
        labelColor="white",
        titleColor="white"
    ).configure_title(
        color="white"
    ).configure_view(
        fill="black"
    )

    return chart

def pct_above(df, stat, line):
    return (df[stat] > line).sum() / len(df) * 100

if st.button("Fetch Stats"):
    with st.spinner("Fetching data..."):
        player_id = get_player_id(player_name)
        if not player_id:
            st.error("Player not found. Please check the name.")
        else:
            try:
                stats_df = get_last_10_games(player_id)
                stats_df["GAME_DATE"] = stats_df["GAME_DATE"].dt.date

                # Get player position and simplify slot
                position = get_player_position(player_id)
                slot = simplify_slot(position)

                # Get DvP table and matchup multiplier
                dvp_table = get_dvp_table()
                guard_avg = dvp_table['Guard Pts Allowed'].mean()
                guard_std = dvp_table['Guard Pts Allowed'].std()
                forward_avg = dvp_table['Forward Pts Allowed'].mean()
                forward_std = dvp_table['Forward Pts Allowed'].std()
                center_avg = dvp_table['Center Pts Allowed'].mean()
                center_std = dvp_table['Center Pts Allowed'].std()

                team_map = {
                    'ATL': 'Atlanta Hawks', 'BOS': 'Boston Celtics', 'BKN': 'Brooklyn Nets',
                    'CHA': 'Charlotte Hornets', 'CHI': 'Chicago Bulls', 'CLE': 'Cleveland Cavaliers',
                    'DAL': 'Dallas Mavericks', 'DEN': 'Denver Nuggets', 'DET': 'Detroit Pistons',
                    'GSW': 'Golden State Warriors', 'HOU': 'Houston Rockets', 'IND': 'Indiana Pacers',
                    'LAC': 'LA Clippers', 'LAL': 'Los Angeles Lakers', 'MEM': 'Memphis Grizzlies',
                    'MIA': 'Miami Heat', 'MIL': 'Milwaukee Bucks', 'MIN': 'Minnesota Timberwolves',
                    'NOP': 'New Orleans Pelicans', 'NYK': 'New York Knicks', 'OKC': 'Oklahoma City Thunder',
                    'ORL': 'Orlando Magic', 'PHI': 'Philadelphia 76ers', 'PHX': 'Phoenix Suns',
                    'POR': 'Portland Trail Blazers', 'SAC': 'Sacramento Kings', 'SAS': 'San Antonio Spurs',
                    'TOR': 'Toronto Raptors', 'UTA': 'Utah Jazz', 'WAS': 'Washington Wizards'
                }

                team_name = team_map.get(opponent_abbr)
                if team_name and team_name in dvp_table["TEAM_NAME"].values:
                    dvp_row = dvp_table[dvp_table["TEAM_NAME"] == team_name].iloc[0]
                    matchup_score = get_matchup_score(
                        dvp_row, slot,
                        guard_avg, guard_std,
                        forward_avg, forward_std,
                        center_avg, center_std
                    )
                    st.metric(label="📊 Matchup Multiplier", value=f"{matchup_score:.2f}x")
                else:
                    st.warning("Could not find DvP data for selected opponent.")

                # Headshot and team logo
                headshot_url = f"https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png"
                team_logos = {
                    "ATL": "https://cdn.nba.com/logos/nba/1610612737/global/L/logo.svg",
                    "BOS": "https://cdn.nba.com/logos/nba/1610612738/global/L/logo.svg",
                    "BKN": "https://cdn.nba.com/logos/nba/1610612751/global/L/logo.svg",
                    "CHA": "https://cdn.nba.com/logos/nba/1610612766/global/L/logo.svg",
                    "CHI": "https://cdn.nba.com/logos/nba/1610612741/global/L/logo.svg",
                    "CLE": "https://cdn.nba.com/logos/nba/1610612739/global/L/logo.svg",
                    "DAL": "https://cdn.nba.com/logos/nba/1610612742/global/L/logo.svg",
                    "DEN": "https://cdn.nba.com/logos/nba/1610612743/global/L/logo.svg",
                    "DET": "https://cdn.nba.com/logos/nba/1610612765/global/L/logo.svg",
                    "GSW": "https://cdn.nba.com/logos/nba/1610612744/global/L/logo.svg",
                    "HOU": "https://cdn.nba.com/logos/nba/1610612745/global/L/logo.svg",
                    "IND": "https://cdn.nba.com/logos/nba/1610612754/global/L/logo.svg",
                    "LAC": "https://cdn.nba.com/logos/nba/1610612746/global/L/logo.svg",
                    "LAL": "https://cdn.nba.com/logos/nba/1610612747/global/L/logo.svg",
                    "MEM": "https://cdn.nba.com/logos/nba/1610612763/global/L/logo.svg",
                    "MIA": "https://cdn.nba.com/logos/nba/1610612748/global/L/logo.svg",
                    "MIL": "https://cdn.nba.com/logos/nba/1610612749/global/L/logo.svg",
                    "MIN": "https://cdn.nba.com/logos/nba/1610612750/global/L/logo.svg",
                    "NOP": "https://cdn.nba.com/logos/nba/1610612740/global/L/logo.svg",
                    "NYK": "https://cdn.nba.com/logos/nba/1610612752/global/L/logo.svg",
                    "OKC": "https://cdn.nba.com/logos/nba/1610612760/global/L/logo.svg",
                    "ORL": "https://cdn.nba.com/logos/nba/1610612753/global/L/logo.svg",
                    "PHI": "https://cdn.nba.com/logos/nba/1610612755/global/L/logo.svg",
                    "PHX": "https://cdn.nba.com/logos/nba/1610612756/global/L/logo.svg",
                    "POR": "https://cdn.nba.com/logos/nba/1610612757/global/L/logo.svg",
                    "SAC": "https://cdn.nba.com/logos/nba/1610612758/global/L/logo.svg",
                    "SAS": "https://cdn.nba.com/logos/nba/1610612759/global/L/logo.svg",
                    "TOR": "https://cdn.nba.com/logos/nba/1610612761/global/L/logo.svg",
                    "UTA": "https://cdn.nba.com/logos/nba/1610612762/global/L/logo.svg",
                    "WAS": "https://cdn.nba.com/logos/nba/1610612764/global/L/logo.svg"
                }
                team_abbr = stats_df.iloc[0]["MATCHUP"].split(" ")[0]
                logo_url = team_logos.get(team_abbr)

                col1, col2 = st.columns([2, 1])
                with col1:
                    st.image(headshot_url, caption=player_name, width=200)
                with col2:
                    if logo_url:
                        st.image(logo_url, caption=f"{team_abbr} Logo", width=100)

                st.success(f"Showing last 10 games for {player_name}")
                st.dataframe(stats_df, use_container_width=True)

                for stat, line in [("PTS", pts_line), ("REB", reb_line), ("AST", ast_line), ("MIN", min_line)]:
                    st.markdown(f"### {stat}")
                    st.altair_chart(stat_chart(stats_df, stat, line), use_container_width=True)
                    st.caption(f"{pct_above(stats_df, stat, line):.1f}% of games over {line} {stat.lower()}")

            except Exception as e:

                st.error(f"Error fetching data: {e}")
