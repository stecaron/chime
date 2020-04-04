library(rvest)
library(data.table)


url <- "https://www.inspq.qc.ca/covid-19/donnees"
covid <- read_html(url)

#covid %>% html_structure()
