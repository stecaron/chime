"""Models.

Changes affecting results or their presentation should also update
parameters.py `change_date`, so users can see when results have last
changed
"""

from __future__ import annotations

from typing import Dict, Generator, Tuple, Optional
from datetime import date, datetime

import numpy as np  # type: ignore
import pandas as pd  # type: ignore

from .parameters import Parameters

EPSILON = 1.0e-7


class SimSirModel:

    def __init__(self, p: Parameters):

        # BEGIN FIX PARAMETERS FOR TEST
        #p.n_days = 100
        #p.date_first_hospitalized = date(year=2020, month=3, day=7)
        #p.doubling_time = None
        # END FIX



        if p.date_first_hospitalized:
            n_days_since = (p.today - p.date_first_hospitalized).days
            print("%s: %s - %s = %s days" % (
                datetime.now(),
                p.today, p.date_first_hospitalized,
                n_days_since,
            ))

        rates = {
            key: d.rate
            for key, d in p.dispositions.items()
        }

        lengths_of_stay = {
            key: d.length_of_stay
            for key, d in p.dispositions.items()
        }

        # Note: this should not be an integer.
        # We're appoximating infected from what we do know.
        # TODO market_share > 0, hosp_rate > 0
        infected = (
            p.current_hospitalized / p.market_share / p.hospitalized.rate
        )

        susceptible = p.population - infected

        detection_probability = (
            p.known_infected / infected if infected > EPSILON else None
        )

        intrinsic_growth_rate = get_growth_rate(p.doubling_time)

        gamma = 1.0 / p.recovery_days

        # Contact rate, beta
        beta = (
            (intrinsic_growth_rate + gamma)
            / susceptible
            * (1.0 - p.relative_contact_rate)
        )  # {rate based on doubling time} / {initial susceptible}

        # r_t is r_0 after distancing
        r_t = beta / gamma * susceptible

        # Simplify equation to avoid division by zero:
        # self.r_naught = r_t / (1.0 - relative_contact_rate)
        r_naught = (intrinsic_growth_rate + gamma) / gamma
        doubling_time_t = 1.0 / np.log2(
            beta * susceptible - gamma + 1)

        raw_df = sim_sir_df(
            susceptible,
            infected,
            p.recovered,
            beta,
            gamma,
            p.n_days,
        )
        dispositions_df = build_dispositions_df(raw_df, rates, p.market_share)
        admits_df = build_admits_df(dispositions_df)
        census_df = build_census_df(admits_df, lengths_of_stay)

        self.susceptible = susceptible
        self.infected = infected
        self.recovered = p.recovered

        self.detection_probability = detection_probability
        self.intrinsic_growth_rate = intrinsic_growth_rate
        self.gamma = gamma
        self.beta = beta
        self.r_t = r_t
        self.r_naught = r_naught
        self.doubling_time_t = doubling_time_t
        #self.raw_df = raw_df
        #self.dispositions_df = dispositions_df
        #self.admits_df = admits_df
        #self.census_df = census_df

        if p.date_first_hospitalized is None and p.doubling_time is not None:
            print('%s: use doubling_time.' % (datetime.now(),))
            n_days_since = int(get_argmin_ds(census_df, p.current_hospitalized))

            raw_df = sim_sir_df(
                susceptible,
                infected,
                p.recovered,
                beta,
                gamma,
                p.n_days + n_days_since,
                -n_days_since,
            )
            dispositions_df = build_dispositions_df(raw_df, rates, p.market_share)
            admits_df = build_admits_df(dispositions_df)
            census_df = build_census_df(census_df, lengths_of_stay)

            print(raw_df)

        elif p.date_first_hospitalized is not None and p.doubling_time is None:
            print('%s: using date_first_hospitalized.' % (datetime.now(),))
            min_loss = 2.0**99
            dt = census_df = current_infected = None
            for i_dt in np.linspace(1,15,29):
                i_census_df, i_current_infected = get_census_and_infected_projection(
                    rates,
                    lengths_of_stay,
                    n_days_since,
                    i_dt,
                    p)
                loss = get_loss(i_census_df, p.current_hospitalized, n_days_since)
                if loss < min_loss:
                    min_loss = loss
                    dt, census_df, current_infected = i_dt, i_census_df, i_current_infected
            p.doubling_time = dt

            infected = 1 / p.hospitalized.rate / p.market_share
            # update all state that is dependent on doubling time.
            intrinsic_growth_rate = get_growth_rate(p.doubling_time)
            gamma = 1 / p.recovery_days
            beta = get_beta(intrinsic_growth_rate, gamma, susceptible, p.relative_contact_rate)
            r_t = beta / gamma * susceptible
            r_naught = (intrinsic_growth_rate + gamma) / gamma
            doubling_time_t = 1.0 / np.log2(beta * susceptible - gamma + 1)
            raw_df = sim_sir_df(
                susceptible,
                current_infected,
                p.recovered,
                beta,
                gamma,
                p.n_days + n_days_since,
                -n_days_since,
            )
            dispositions_df = build_dispositions_df(raw_df, rates, p.market_share)
            admits_df = build_admits_df(dispositions_df)
            census_df = build_census_df(admits_df, lengths_of_stay)

            self.population = p.population
            self.infected = current_infected
            self.intrinsic_growth_rate = intrinsic_growth_rate
            self.gamma = gamma
            self.beta = beta
            self.r_t = r_t
            self.r_naught = r_naught
            self.doubling_time_t = doubling_time_t

            print(raw_df)

        else:
            raise AssertionError('doubling_time or date_first_hospitalized must be provided.')

        self.raw_df = raw_df
        self.dispositions_df = dispositions_df
        self.admits_df = admits_df
        self.census_df = census_df

        self.daily_growth_rate = get_growth_rate(p.doubling_time)
        self.daily_growth_rate_t = get_growth_rate(doubling_time_t)


def get_census_and_infected_projection(
    rates: Dict[str: float],
    lengths_of_stay: Dict[str: int],
    n_days_since: int,
    doubling_time: float,
    p: Parameters
) -> Tuple[pd.DataFrame, float]:
    intrinsic_growth_rate = get_growth_rate(doubling_time)

    initial_i = 1.0 / p.hospitalized.rate / p.market_share

    S, I, R = p.population - initial_i, initial_i, p.recovered

    # mean recovery rate (inv_recovery_days)
    gamma = 1.0 / p.recovery_days

    # contact rate
    beta = (intrinsic_growth_rate + gamma) / S

    n_days = p.n_days

    raw_df = sim_sir_df(
        S, I, R, beta, gamma,
        p.n_days + n_days_since,
        -n_days_since
    )

    current_infected = raw_df.infected.loc[n_days_since]
    dispositions_df = build_dispositions_df(raw_df, rates, p.market_share)

    admits_df = build_admits_df(dispositions_df)
    census_df = build_census_df(admits_df, lengths_of_stay)
    return census_df, current_infected


def get_argmin_ds(census_df: pd.DataFrame, current_hospitalized: float) -> float:
    losses_df = (census_df.hospitalized - current_hospitalized) ** 2.0
    return losses_df.argmin()


def get_beta(
    intrinsic_growth_rate: float,
    gamma: float,
    susceptible: float,
    relative_contact_rate: float
) -> float:
    return (
        (intrinsic_growth_rate + gamma)
        / susceptible
        * (1.0 - relative_contact_rate)
    )


def get_growth_rate(doubling_time: Optional[float]) -> float:
    """Calculates average daily growth rate from doubling time."""
    if doubling_time is None or doubling_time == 0.0:
        return 0.0
    return (2.0 ** (1.0 / doubling_time) - 1.0)


def get_loss(census_df: DataFrame, current_hospitalized: float, n_days_since: int) -> float:
    """Squared error: predicted vs. actual current hospitalized."""
    predicted = census_df.hospitalized.loc[n_days_since]
    return (current_hospitalized - predicted) ** 2.0


def sir(
    s: float, i: float, r: float, beta: float, gamma: float, n: float
) -> Tuple[float, float, float]:
    """The SIR model, one time step."""
    s_n = (-beta * s * i) + s
    i_n = (beta * s * i - gamma * i) + i
    r_n = gamma * i + r
    if s_n < 0.0:
        s_n = 0.0
    if i_n < 0.0:
        i_n = 0.0
    if r_n < 0.0:
        r_n = 0.0

    scale = n / (s_n + i_n + r_n)
    return s_n * scale, i_n * scale, r_n * scale


def gen_sir(
    s: float, i: float, r: float,
    beta: float, gamma: float, n_days: int, i_day: int = 0
) -> Generator[Tuple[int, float, float, float], None, None]:
    """Simulate SIR model forward in time yielding tuples."""
    s, i, r = (float(v) for v in (s, i, r))
    n = s + i + r
    d = i_day
    for _ in range(n_days):
        yield d, s, i, r
        s, i, r = sir(s, i, r, beta, gamma, n)
        d += 1
    yield d, s, i, r


def sim_sir_df(
    s: float, i: float, r: float, beta: float, gamma: float, n_days: int, i_day: int = 0
) -> pd.DataFrame:
    """Simulate the SIR model forward in time."""
    dat = pd.DataFrame(
        data=gen_sir(s, i, r, beta, gamma, n_days, i_day),
        columns=("day", "susceptible", "infected", "recovered"),
    )
    return dat


def get_dispositions(
    patients: np.ndarray,
    rates: Dict[str, float],
    market_share: float,
) -> Dict[str, np.ndarray]:
    """Get dispositions of patients adjusted by rate and market_share."""
    return {
        key: patients * rate * market_share
        for key, rate in rates.items()
    }


def build_dispositions_df(
    sim_sir_df: pd.DataFrame,
    rates: Dict[str, float],
    market_share: float,
) -> pd.DataFrame:
    """Get dispositions of patients adjusted by rate and market_share."""
    patients = sim_sir_df.infected + sim_sir_df.recovered
    return pd.DataFrame({
        "day": sim_sir_df.day,
        **{
            key: patients * rate * market_share
            for key, rate in rates.items()
        }
    })


def build_admits_df(dispositions_df: pd.DataFrame) -> pd.DataFrame:
    """Build admits dataframe from dispositions."""
    admits_df = dispositions_df.iloc[:-1, :] - dispositions_df.shift(1)
    admits_df.day = dispositions_df.day
    return admits_df


def build_census_df(
    admits_df: pd.DataFrame,
    lengths_of_stay: Dict[str, int],
) -> pd.DataFrame:
    """Average Length of Stay for each disposition of COVID-19 case (total guesses)"""
    return pd.DataFrame({
        'day': admits_df.day,
        **{
            key: (
                admits_df[key].cumsum().iloc[:-los]
                - admits_df[key].cumsum().shift(los).fillna(0)
            ).apply(np.ceil)
            for key, los in lengths_of_stay.items()
        }
    })



