### MIGHT BE ABLE TO DO THAT WITH RSelenium


library(rvest)
library(data.table)

url <- "https://www.inspq.qc.ca/covid-19/donnees"
covidQC <- read_html(url)

scripts <- covidQC %>% 
  html_nodes("script")

scripts <- scripts[44:50]
