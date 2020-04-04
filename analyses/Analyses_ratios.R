
### load packages

library(tidyverse)


### import data

data_hosp <- data.table::fread("data/qc_hosp_icu.csv")
data_covid <- data.table::fread("data/covid19.csv")


### Prep data for merge + merge

data_hosp <- data_hosp %>%
  mutate(Date = as.Date(Date, "%Y-%m-%d"))

data_qc_combined <- data_covid %>%
  mutate(date = as.Date(date, "%d-%m-%Y")) %>%
  filter(prname == "Quebec") %>%
  left_join(data_hosp, by = c("date" = "Date")) %>%
  filter(!is.na(hosp))

### Calculate ratios

data_qc <- data_qc_combined %>%
  mutate(ratio_hosp = hosp/numtotal,
         ratio_icu = icu/numtotal)



