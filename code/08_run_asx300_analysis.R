# ASX 300: reproducible daily-data preparation and window-level regressions
# Run with Rscript run_asx300_analysis.R /path/to/output /path/to/results
# Or open in RStudio, set INPUT_DIR below, and Source the entire file.
# No matching is re-run. The six CSVs must already contain matched groups.

INPUT_DIR <- ""             # Folder containing review_01.csv ... review_06.csv
OUTPUT_DIR <- ""            # Empty: create a results subfolder of INPUT_DIR
CAP_SPEC <- "baseline"      # Main regression: "baseline" or "reference"
RUN_REFERENCE_COMPARISON <- TRUE
RUN_LEAVE_ONE_REVIEW_OUT <- TRUE
RUN_STRICT_80 <- TRUE
VERIFY_WITH_DUMMY_WLS <- TRUE
MIN_WINDOW_COVERAGE <- 0.60
MIN_EP_RETURNS <- 12L
MIN_BASELINE_CAP_DAYS <- 12L

needed <- c("dplyr", "tidyr", "ggplot2", "sandwich")
missing <- needed[!vapply(needed, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing)) stop("Install missing packages first: install.packages(c(",
  paste(sprintf('"%s"', missing), collapse = ", "), "))", call. = FALSE)
suppressPackageStartupMessages({library(dplyr); library(tidyr); library(ggplot2)})
args <- commandArgs(trailingOnly = TRUE)
if (length(args) >= 1L) INPUT_DIR <- args[1]
if (length(args) >= 2L) OUTPUT_DIR <- args[2]
filenames <- sprintf("review_%02d.csv", 1:6)
script_path <- sub("^--file=", "", grep("^--file=", commandArgs(), value = TRUE))
if (!length(script_path)) {
  ofiles <- lapply(sys.frames(), function(x) x$ofile)
  ofiles <- Filter(function(x) is.character(x) && length(x) == 1L, ofiles)
  if (length(ofiles)) script_path <- tail(ofiles, 1L)[[1L]]
}
script_dir <- if (length(script_path)) dirname(normalizePath(script_path[1], mustWork = FALSE)) else getwd()
has_inputs <- function(x) length(x) == 1L && nzchar(x) && all(file.exists(file.path(x, filenames)))
if (!nzchar(INPUT_DIR)) {
  candidates <- unique(c(
    file.path(getwd(), "data", "derived"),
    file.path(script_dir, "..", "data", "derived"),
    getwd(), script_dir, file.path(getwd(), "output"),
    file.path(script_dir, "output"), file.path(script_dir, "data"),
    Sys.getenv("ASX300_INPUT_DIR")
  ))
  found <- candidates[vapply(candidates, has_inputs, logical(1))]
  if (length(found)) INPUT_DIR <- found[1L]
}
if (!has_inputs(INPUT_DIR)) stop("Set INPUT_DIR to the folder containing ALL six review_01.csv ... review_06.csv files.", call. = FALSE)
INPUT_DIR <- normalizePath(INPUT_DIR)
CAP_SPEC <- match.arg(CAP_SPEC, c("baseline", "reference"))
repo_root <- normalizePath(file.path(script_dir, ".."), mustWork = FALSE)
if (!nzchar(OUTPUT_DIR)) {
  if (dir.exists(file.path(repo_root, "output", "tables"))) {
    OUTPUT_DIR <- file.path(repo_root, "output", "tables")
  } else {
    OUTPUT_DIR <- file.path(INPUT_DIR, paste0("asx300_results_", CAP_SPEC, "_cap"))
  }
}
dir.create(OUTPUT_DIR, recursive = TRUE, showWarnings = FALSE)
od <- normalizePath(OUTPUT_DIR)
fig_dir <- if (dir.exists(file.path(repo_root, "output", "figures"))) normalizePath(file.path(repo_root, "output", "figures")) else od
log_dir <- if (dir.exists(file.path(repo_root, "output", "logs"))) normalizePath(file.path(repo_root, "output", "logs")) else od
files <- file.path(INPUT_DIR, filenames)
write_out <- function(x, name) write.csv(as.data.frame(x), file.path(od, name), row.names = FALSE, na = "")
finite_mean <- function(x) if (any(is.finite(x))) mean(x[is.finite(x)]) else NA_real_
required <- c("stock_id", "trading_date", "treatment", "matched_group_id", "event_day",
  "close", "volume", "daily_return", "daily_market_cap_aud", "reference_market_cap_aud")
loaded <- lapply(seq_along(files), function(i) {
  x <- read.csv(files[i], stringsAsFactors = FALSE, check.names = FALSE, na.strings = c("", "NA", "NaN", "null"))
  names(x) <- trimws(sub("^\\ufeff", "", names(x)))
  absent <- setdiff(required, names(x))
  if (length(absent)) stop(basename(files[i]), " is missing: ", paste(absent, collapse = ", "))
  id <- sprintf("R%02d", i)
  if ("review_id" %in% names(x) && any(!is.na(x$review_id) & x$review_id != id)) stop("Review IDs disagree with filename: ", basename(files[i]))
  x$review_id <- id; x$source_file <- basename(files[i]); x
})
d <- bind_rows(loaded)
if (anyDuplicated(d[c("review_id", "stock_id", "trading_date")])) stop("Duplicate stock-review-date rows found; do not silently average duplicates.")
for (v in c("treatment", "event_day", "close", "volume", "daily_return", "daily_market_cap_aud", "reference_market_cap_aud")) d[[v]] <- suppressWarnings(as.numeric(d[[v]]))
if (anyNA(d$event_day) || any(d$event_day != round(d$event_day))) stop("event_day must be a valid integer.")
if (anyNA(d$treatment) || any(!d$treatment %in% 0:1)) stop("treatment must be 0 or 1.")
if (anyNA(d$matched_group_id) || anyNA(d$stock_id) || anyNA(d$trading_date)) stop("Missing panel identifiers.")
d <- d %>% filter(between(event_day, -60, 60)) %>%
  mutate(matched_group_id_original = matched_group_id,
         matched_group_id = paste(review_id, matched_group_id, sep = ":"),
         unit = paste(review_id, stock_id, sep = ":"))
if (anyDuplicated(d[c("unit", "event_day")])) stop("Duplicate event_day within a stock-review.")
ph <- c("EP", "B", "PA", "AP", "SP", "LP"); ks <- setdiff(ph, "B"); revs <- sprintf("R%02d", 1:6)
expected_days <- c(EP = 20L, B = 20L, PA = 21L, AP = 10L, SP = 20L, LP = 30L)
schedule <- data.frame(phase = ph, first_day = c(-60,-40,-20,1,11,31), last_day = c(-41,-21,0,10,30,60), expected_days = as.integer(expected_days))
write_out(schedule, "stage_schedule.csv")
d <- d %>% mutate(volume_original = volume, zero_volume = !is.na(volume) & volume == 0,
  valid_trade = is.finite(volume) & volume > 0 & is.finite(close) & close > 0,
  volume = ifelse(valid_trade, volume, NA_real_),
  amihud_source = if ("amihud" %in% names(d)) as.numeric(d$amihud) else NA_real_,
  amihud = ifelse(valid_trade & is.finite(daily_return), abs(daily_return)/(close*volume)*1e6, NA_real_),
  phase = case_when(event_day <= -41 ~ "EP", event_day <= -21 ~ "B", event_day <= 0 ~ "PA",
                    event_day <= 10 ~ "AP", event_day <= 30 ~ "SP", TRUE ~ "LP"))
# No filling. Zero volume is invalid for Amihud; genuine zero returns remain A=0.
# Logs are taken AFTER window averaging. Never replace a zero return by an epsilon.
write_out(d %>% group_by(review_id, treatment) %>% summarise(rows=n(), zero_volume=sum(zero_volume),
  invalid_amihud=sum(!is.finite(amihud)), zero_amihud=sum(amihud==0,na.rm=TRUE), .groups="drop"), "daily_QA.csv")
write_out(d %>% filter(is.finite(amihud_source), is.finite(amihud), abs(amihud_source-amihud)>1e-7) %>%
  select(review_id,stock_id,trading_date,amihud_source,amihud), "source_amihud_disagreements.csv")
identity_check <- d %>% group_by(unit) %>% summarise(n_group=n_distinct(matched_group_id), n_treatment=n_distinct(treatment),
  n_ref=n_distinct(reference_market_cap_aud[is.finite(reference_market_cap_aud)]), .groups="drop")
if (any(identity_check$n_group != 1 | identity_check$n_treatment != 1 | identity_check$n_ref != 1)) stop("Within-review stock reuse, treatment inconsistency, or inconsistent reference cap found.")
unit <- d %>% distinct(unit, .keep_all=TRUE)
group_structure <- unit %>% group_by(matched_group_id) %>% summarise(n_stock=n(), n_treated=sum(treatment), .groups="drop")
write_out(group_structure, "matched_group_structure.csv")
if (any(group_structure$n_stock != 3 | group_structure$n_treated != 1)) stop("Each matched group must contain exactly one addition and two controls.")
cap <- d %>% filter(phase == "B") %>% group_by(unit) %>% summarise(
  n_cap_B=sum(is.finite(daily_market_cap_aud) & daily_market_cap_aud > 0),
  cap_B=finite_mean(ifelse(is.finite(daily_market_cap_aud) & daily_market_cap_aud > 0,daily_market_cap_aud,NA_real_)), .groups="drop")
vol <- d %>% filter(phase == "EP") %>% group_by(unit) %>% summarise(
  vol_EP=100*sd(daily_return[is.finite(daily_return)]), n_ret=sum(is.finite(daily_return)), .groups="drop")
controls <- unit %>% select(unit,review_id,matched_group_id,stock_id,treatment,reference_market_cap_aud) %>%
  left_join(cap,by="unit") %>% left_join(vol,by="unit") %>%
  mutate(logcap_baseline=log(cap_B), logcap_reference=log(reference_market_cap_aud))
write_out(controls, "stock_review_covariates.csv")
# P99 robustness: ONE daily upper cap from EP+B (-60:-21), pooled across both groups and all reviews.
# Main regression is UNCAPPED. Apply the cap before window averaging; do not cap separately by post window.
cutoff <- unname(quantile(d$amihud[d$event_day<=-21 & is.finite(d$amihud)], .99, type=7))
d <- d %>% mutate(amihud_w=pmin(amihud, cutoff))
write_out(data.frame(pre_period="-60:-21", quantile=.99, daily_amihud_cap=cutoff), "p99_cutoff.csv")
window_values <- d %>% group_by(unit,phase) %>% summarise(raw=finite_mean(amihud), win=finite_mean(amihud_w),
  n_valid=sum(is.finite(amihud)), n_rows=n(), .groups="drop")
# Missing dates count against the EXPECTED window length, not just rows present in the CSV.
# Make missing entire windows explicit before deciding group eligibility.
s_all <- tidyr::crossing(unit=unit$unit,phase=ph) %>% left_join(window_values,by=c("unit","phase")) %>%
  left_join(controls,by="unit") %>% mutate(n_valid=coalesce(n_valid,0L),n_rows=coalesce(n_rows,0L),
  n_days=as.integer(expected_days[phase]), coverage=n_valid/n_days,
  ok_outcome=coverage>=MIN_WINDOW_COVERAGE & is.finite(raw) & raw>0 & is.finite(win) & win>0,
  ok_vol=n_ret>=MIN_EP_RETURNS & is.finite(vol_EP),
  ok_baseline_cap=n_cap_B>=MIN_BASELINE_CAP_DAYS & is.finite(logcap_baseline),
  ok_reference_cap=is.finite(logcap_reference),
  ok_cap=if(CAP_SPEC=="baseline") ok_baseline_cap else ok_reference_cap,
  ok=ok_outcome & ok_vol & ok_cap)
# A fixed common sample makes baseline/reference coefficients directly comparable.
if (RUN_REFERENCE_COMPARISON) s_all$ok <- s_all$ok & s_all$ok_baseline_cap & s_all$ok_reference_cap
write_out(s_all %>% filter(!ok), "invalid_stock_windows.csv")
group_qa <- s_all %>% group_by(matched_group_id) %>% summarise(retain=all(ok) & n()==18L,.groups="drop")
write_out(group_qa, "group_eligibility.csv")
s <- s_all %>% filter(matched_group_id %in% group_qa$matched_group_id[group_qa$retain]) %>%
  mutate(phase=factor(phase,levels=ph),logcap=if(CAP_SPEC=="baseline") logcap_baseline else logcap_reference,
         ln=log(raw),lnwin=log(win),w=ifelse(treatment==1,1,.5)) %>% arrange(review_id,matched_group_id,stock_id,phase)
if (!nrow(s) || !setequal(unique(s$review_id),revs)) stop("No eligible complete sample spanning all six reviews. See QA CSVs.")
counts <- s %>% distinct(unit,.keep_all=TRUE) %>% group_by(review_id) %>% summarise(additions=sum(treatment==1),controls=sum(treatment==0),.groups="drop") %>% mutate(weight=additions/sum(additions))
write_out(counts, "sample_counts_and_review_weights.csv")
write_out(d, "clean_daily.csv"); write_out(s, "regression_panel.csv")
message("Input: ",INPUT_DIR,"\nResults: ",od,"\nMain cap: ",CAP_SPEC,"; retained groups: ",n_distinct(s$matched_group_id))

# Helper sourced by run_asx300_analysis.R.
# Weighted FWL is valid here because complete matched groups and balanced
# stock-review-window panels are retained, with constant stock-review weights.
# Weighted FWL with complete unit x window panels and constant unit weights.
fit_model <- function(dat,outcome='ln',hetero=TRUE,adjust=TRUE,windows=ph,ref='B'){
 dat <- dat %>% arrange(review_id,matched_group_id,stock_id,phase)
 active <- unique(dat$review_id);win <- setdiff(windows,ref)
 gw <- paste(dat$matched_group_id,dat$phase,sep=':');ug <- dat$matched_group_id
 N <- nrow(dat);G <- n_distinct(dat$stock_id)
 stopifnot(all(table(dat$unit)==length(windows)))
 fe <- function(z){z<-as.matrix(z);out<-z;for(j in seq_len(ncol(z))){v<-z[,j];um<-ave(v,dat$unit,FUN=mean);gm<-rowsum(v*dat$w,ug,reorder=FALSE)/rowsum(dat$w,ug,reorder=FALSE);wm<-rowsum(v*dat$w,gw,reorder=FALSE)/rowsum(dat$w,gw,reorder=FALSE);out[,j]<-v-um-wm[gw,1]+gm[ug,1]};out}
 xx <- list()
 if(hetero)for(r in active)for(k in win)xx[[paste0('b_',r,'_',k)]] <- as.numeric(dat$review_id==r & dat$phase==k)*dat$treatment
 if(!hetero)for(k in win)xx[[paste0('b_',k)]] <- as.numeric(dat$phase==k)*dat$treatment
 if(adjust)for(k in win){xx[[paste0('cap_',k)]]<-as.numeric(dat$phase==k)*dat$logcap;xx[[paste0('vol_',k)]]<-as.numeric(dat$phase==k)*dat$vol_EP}
 xr <- as.matrix(as.data.frame(xx));X<-fe(xr);Y<-fe(dat[[outcome]])[,1]
 m<-lm.wfit(X,Y,dat$w);stopifnot(m$rank==ncol(X))
 b<-m$coefficients;names(b)<-colnames(X);K<-n_distinct(dat$unit)+n_distinct(ug)*(length(windows)-1)+ncol(X)
 bread<-solve(crossprod(X,dat$w*X));score<-rowsum(X*as.numeric(dat$w*m$residuals),dat$stock_id,reorder=FALSE)
 V<-bread%*%crossprod(score)%*%bread*G/(G-1)*(N-1)/(N-K);dimnames(V)<-list(names(b),names(b))
 ct<-dat %>% distinct(unit,.keep_all=TRUE) %>% filter(treatment==1) %>% count(review_id)
 wr<-setNames(ct$n/sum(ct$n),ct$review_id)
 A<-matrix(0,length(win),length(b),dimnames=list(win,names(b)))
 for(k in win){if(hetero)for(r in active)A[k,paste0('b_',r,'_',k)]<-wr[[r]] else A[k,paste0('b_',k)]<-1}
 sm<-function(bb,vv,terms){se<-sqrt(pmax(diag(vv),0));cv<-qt(.975,G-1);data.frame(term=terms,beta=as.numeric(bb),se=se,lo=as.numeric(bb)-cv*se,hi=as.numeric(bb)+cv*se,p=2*pt(-abs(as.numeric(bb)/se),G-1))}
 ag<-sm(A%*%b,A%*%V%*%t(A),win);ag$p_holm<-p.adjust(ag$p,'holm')
 if(outcome!='raw')ag<-ag %>% mutate(effect_pct=100*expm1(beta),lo_pct=100*expm1(lo),hi_pct=100*expm1(hi))
 ix<-grep('^b_',names(b));co<-sm(b[ix],V[ix,ix,drop=FALSE],names(b)[ix])
 co$phase<-sub('.*_','',co$term);co$review_id<-if(hetero)sub('^b_(R[0-9]+)_.*','\\1',co$term) else 'Pooled'
 wald<-function(R,label){q<-nrow(R);bb<-R%*%b;vv<-R%*%V%*%t(R);stopifnot(min(eigen(vv,symmetric=TRUE,only.values=TRUE)$values)>0);f<-as.numeric(t(bb)%*%solve(vv,bb)/q);data.frame(test=label,F=f,df1=q,df2=G-1,p=pf(f,q,G-1,lower.tail=FALSE))}
 tests<-list()
 if(all(c('SP','LP')%in%win))tests[['persistence']]<-wald(A[c('SP','LP'),,drop=FALSE],'Aggregated SP=LP=0')
 if(hetero){
  equality<-function(wins){R<-matrix(0,(length(active)-1)*length(wins),length(b));z<-0;for(k in wins)for(r in active[-1]){z<-z+1;R[z,match(paste0('b_',r,'_',k),names(b))]<-1;R[z,match(paste0('b_',active[1],'_',k),names(b))]<- -1};R}
  for(k in win)tests[[k]]<-wald(equality(k),paste0('Review equality: ',k))
  if(all(c('AP','SP','LP')%in%win))tests[['post']]<-wald(equality(c('AP','SP','LP')),'Review equality: AP SP LP')
  tests[['all']]<-wald(equality(win),'Review equality: all windows')
 }
 list(b=b,V=V,A=A,aggregate=ag,coefficients=co,tests=bind_rows(tests),N=N,clusters=G,rank=K,groups=n_distinct(ug),dat=dat,xr=xr,wald=wald)
}


# Main, pooled benchmark, unadjusted models and raw/P99 outcome sensitivity.
fits<-list();ags<-list();cos<-list();ts<-list()
for(y in c('ln','raw','lnwin')) for(het in c(FALSE,TRUE)) for(adj in c(FALSE,TRUE)) {
  key<-paste(y,ifelse(het,'het','hom'),ifelse(adj,'X','base'),sep='_')
  z<-fit_model(s,y,het,adj);fits[[key]]<-z
  ags[[key]]<-mutate(z$aggregate,model=key);cos[[key]]<-mutate(z$coefficients,model=key);ts[[key]]<-mutate(z$tests,model=key)
}
agg<-bind_rows(ags);coef_table<-bind_rows(cos);tests<-bind_rows(ts)
write_out(agg,'aggregate_effects_all_models.csv');write_out(coef_table,'review_specific_coefficients.csv');write_out(tests,'homogeneity_and_joint_tests.csv')
main<-fits[['ln_het_X']]
contrast_results <- function(fit) {
  pairs<-list(c('LP','AP'),c('SP','AP'),c('LP','SP'))
  out<-bind_rows(lapply(pairs,function(pair){
    a<-fit$A[pair[1],]-fit$A[pair[2],];beta<-as.numeric(a%*%fit$b);se<-sqrt(as.numeric(a%*%fit$V%*%a));df<-fit$clusters-1;cv<-qt(.975,df)
    data.frame(contrast=paste(pair,collapse=' - '),beta=beta,se=se,effect_pct=100*expm1(beta),
      lo_pct=100*expm1(beta-cv*se),hi_pct=100*expm1(beta+cv*se),p=2*pt(-abs(beta/se),df))
  }));out$p_holm<-p.adjust(out$p,'holm');out
}
write_out(contrast_results(main),'post_window_contrasts.csv')
saveRDS(fits,file.path(od,'fitted_models.rds')) # Includes full V and aggregation matrices A.
if (VERIFY_WITH_DUMMY_WLS) {
  dd<-as.data.frame(main$xr);dd$unit<-factor(s$unit);dd$gw<-interaction(s$matched_group_id,s$phase,drop=TRUE);dd$y<-s$ln
  full<-lm(y~0+unit+gw+.,data=dd,weights=s$w)
  vf<-sandwich::vcovCL(full,cluster=s$stock_id,type='HC1',cadjust=TRUE);bn<-names(main$b)
  verification<-data.frame(max_beta_difference=max(abs(stats::coef(full)[bn]-main$b)),
    max_vcov_difference=max(abs(vf[bn,bn]-main$V)),full_rank=full$rank,FWL_rank=main$rank)
  write_out(verification,'independent_WLS_verification.csv')
  stopifnot(verification$max_beta_difference<1e-7,verification$max_vcov_difference<1e-7,full$rank==main$rank)
}
if (RUN_REFERENCE_COMPARISON) {
  s_other<-s;s_other$logcap<-if(CAP_SPEC=='baseline')s$logcap_reference else s$logcap_baseline
  other_cap<-if(CAP_SPEC=='baseline')'reference' else 'baseline'
  other<-fit_model(s_other,'ln',TRUE,TRUE)
  write_out(bind_rows(mutate(main$aggregate,cap_spec=CAP_SPEC),mutate(other$aggregate,cap_spec=other_cap)), 'cap_specification_comparison.csv')
  write_out(bind_rows(mutate(main$tests,cap_spec=CAP_SPEC),mutate(other$tests,cap_spec=other_cap)), 'cap_specification_joint_tests.csv')
  write_out(bind_rows(mutate(contrast_results(main),cap_spec=CAP_SPEC),mutate(contrast_results(other),cap_spec=other_cap)), 'cap_specification_contrasts.csv')
}
loo<-data.frame()
if (RUN_LEAVE_ONE_REVIEW_OUT) {
  loo<-bind_rows(lapply(revs,function(r)mutate(fit_model(filter(s,review_id!=r),'ln',TRUE,TRUE)$aggregate,omitted=r)))
  write_out(loo,'leave_one_review_out.csv')
}
if (RUN_STRICT_80) {
  strict_groups<-s %>% group_by(matched_group_id) %>% summarise(ok=all(coverage>=.8 & n_ret>=16 & n_cap_B>=16),.groups='drop')
  write_out(strict_groups,'strict80_group_eligibility.csv')
  strict_data<-filter(s,matched_group_id %in% strict_groups$matched_group_id[strict_groups$ok])
  if (setequal(unique(strict_data$review_id),revs)) {
    strict<-fit_model(strict_data,'ln',TRUE,TRUE);write_out(strict$aggregate,'strict80_aggregate_effects.csv')
  } else warning('Strict80 sensitivity cannot retain all six reviews; skipped.')
}
# CPT diagnostic: four 10-day bins over -60:-21. Reference P3=-40:-31.
# PA=-20:0 is excluded because anticipation is allowed there.
pre_values<-d %>% filter(event_day<=-21) %>% mutate(phase=paste0('P',floor((event_day+60)/10)+1)) %>%
  group_by(unit,phase) %>% summarise(raw=finite_mean(amihud),n_valid=sum(is.finite(amihud)),.groups='drop')
retained_units<-s %>% distinct(unit)
pre<-tidyr::crossing(unit=retained_units$unit,phase=paste0('P',1:4)) %>% left_join(pre_values,by=c('unit','phase')) %>%
  left_join(controls,by='unit') %>% mutate(n_valid=coalesce(n_valid,0L),
    logcap=if(CAP_SPEC=='baseline')logcap_baseline else logcap_reference,ln=log(raw),w=ifelse(treatment==1,1,.5),
    ok=n_valid>=6 & is.finite(ln) & n_ret>=MIN_EP_RETURNS & is.finite(vol_EP) & is.finite(logcap))
pg<-pre %>% group_by(matched_group_id) %>% summarise(ok=all(ok)&n()==12L,.groups='drop')
write_out(pre %>% filter(!ok),'pretrend_invalid_stock_bins.csv')
pre<-filter(pre,matched_group_id %in% pg$matched_group_id[pg$ok]);pre$phase<-factor(pre$phase,levels=paste0('P',1:4))
pre_co<-list();pre_tests<-list();pre_review<-NULL
for(het in c(FALSE,TRUE)) {
  key<-if(het)'heterogeneous' else 'pooled';z<-fit_model(pre,'ln',het,TRUE,paste0('P',1:4),'P3')
  pre_co[[key]]<-mutate(z$aggregate,model=key)
  pre_tests[[paste0(key,'_agg')]]<-mutate(z$wald(z$A,'All three aggregated pre-bin changes=0'),model=key)
  if(het){ix<-grep('^b_',names(z$b));R<-diag(length(z$b))[ix,,drop=FALSE]
    pre_tests[['allreview']]<-mutate(z$wald(R,'All 18 review-specific pre-bin changes=0'),model=key);pre_review<-z$coefficients}
}
prec<-bind_rows(pre_co);pret<-bind_rows(pre_tests)
write_out(prec,'pretrend_aggregate_coefficients.csv');write_out(pret,'pretrend_joint_tests.csv');write_out(pre_review,'pretrend_review_coefficients.csv')
# Descriptive statistics: equal stock-review weights within treated/control groups.
ss<-s %>% group_by(phase,treatment) %>% summarise(n=n(),mean=mean(raw),sd=sd(raw),
  p10=quantile(raw,.1),p25=quantile(raw,.25),median=median(raw),p75=quantile(raw,.75),p90=quantile(raw,.9),
  geometric_mean=exp(mean(ln)),p99_capped_mean=mean(win),.groups='drop')
write_out(ss,'amihud_summary_statistics.csv')
theme_set(theme_minimal(base_size=12)+theme(panel.grid.minor=element_blank(),legend.position='bottom'))
savep<-function(name,p,w=8.5,h=4.8) ggsave(file.path(od,paste0(name,'.png')),p,width=w,height=h,dpi=220,bg='white')
plot_main<-agg %>% filter(model %in% c('ln_het_X','ln_hom_X','lnwin_het_X')) %>% mutate(phase=factor(term,levels=ks))
savep('main_p99_homogeneous',ggplot(plot_main,aes(phase,effect_pct,ymin=lo_pct,ymax=hi_pct,color=model))+
  geom_hline(yintercept=0,color='grey60')+geom_pointrange(position=position_dodge(width=.4))+
  labs(x='Window (reference B)',y='100 x [exp(beta)-1], %',title='Main, P99 and pooled benchmark',color=NULL))
savep('review_specific_effects',ggplot(filter(coef_table,model=='ln_het_X') %>% mutate(phase=factor(phase,levels=ks)),
  aes(phase,beta,ymin=lo,ymax=hi))+geom_hline(yintercept=0,color='grey60')+geom_pointrange(color='#117C91')+
  facet_wrap(~review_id)+labs(x='Window (reference B)',y='Log coefficient',title='Conditional heterogeneous effects'))
if(nrow(loo)) savep('leave_one_review_out',ggplot(filter(loo,term%in%c('AP','SP','LP')),
  aes(omitted,effect_pct,ymin=lo_pct,ymax=hi_pct))+geom_hline(yintercept=0,color='grey60')+geom_pointrange(color='#117C91')+
  facet_wrap(~term)+labs(x='Review omitted',y='Relative effect, %',title='Leave one review out'))
pp<-bind_rows(filter(prec,model=='heterogeneous'),data.frame(term='P3',beta=0,se=0,lo=0,hi=0,p=NA,p_holm=NA,effect_pct=0,lo_pct=0,hi_pct=0,model='heterogeneous'))
pp$term<-factor(pp$term,levels=paste0('P',1:4))
savep('conditional_pretrend',ggplot(pp,aes(term,beta,ymin=lo,ymax=hi))+geom_hline(yintercept=0,color='grey60')+
  geom_pointrange(color='#117C91')+scale_x_discrete(labels=c('-60:-51','-50:-41','-40:-31','-30:-21'))+
  labs(x='10-day bin (reference -40:-31)',y='Change in treated-control log gap',title='Pre-trend diagnostic: PA excluded'))
if(RUN_REFERENCE_COMPARISON) {
  cc<-bind_rows(mutate(main$aggregate,cap_spec=CAP_SPEC),mutate(other$aggregate,cap_spec=other_cap)) %>% mutate(term=factor(term,levels=ks))
  savep('baseline_vs_reference_cap',ggplot(cc,aes(term,effect_pct,ymin=lo_pct,ymax=hi_pct,color=cap_spec))+
    geom_hline(yintercept=0,color='grey60')+geom_pointrange(position=position_dodge(width=.3))+
    labs(x='Window',y='Relative effect, %',color='Cap covariate',title='Same sample, different cap measurement period'))
}
# Additional checks used in the final English report.
# Keep samples, covariates and weights fixed unless a sensitivity explicitly
# changes eligibility. Holm correction is repeated within each model/family;
# it is not one joint adjustment across every sensitivity specification.

reversion_checks <- list(
  Main = mutate(contrast_results(main), specification = "Conditional heterogeneous (main)", groups = main$groups),
  P99 = mutate(contrast_results(fits$lnwin_het_X), specification = "P99 daily cap then log", groups = main$groups),
  Homogeneous = mutate(contrast_results(fits$ln_hom_X), specification = "Conditional homogeneous", groups = main$groups)
)
robust_effects <- list(
  Main = mutate(main$aggregate, specification = "Conditional heterogeneous (main)", groups = main$groups),
  P99 = mutate(fits$lnwin_het_X$aggregate, specification = "P99 daily cap then log", groups = main$groups),
  Homogeneous = mutate(fits$ln_hom_X$aggregate, specification = "Conditional homogeneous", groups = main$groups)
)
additional_models <- list()
if (RUN_REFERENCE_COMPARISON) {
  reversion_checks[[other_cap]] <- mutate(contrast_results(other), specification = paste0(other_cap, "-date cap"), groups = other$groups)
  robust_effects[[other_cap]] <- mutate(other$aggregate, specification = paste0(other_cap, "-date cap"), groups = other$groups)
}
if (RUN_STRICT_80 && exists("strict")) {
  reversion_checks$strict <- mutate(contrast_results(strict), specification = "Stricter 80% coverage", groups = strict$groups)
  robust_effects$strict <- mutate(strict$aggregate, specification = "Stricter 80% coverage", groups = strict$groups)
}

# Exclude the Friday rebalance close, day +10, from AP only.
# AP becomes +1:+9, so the coverage denominator is nine days (six required at 60%).
# Do not drop day +11: it is the first day of effective index membership.
ap_without_close <- d %>% filter(unit %in% s$unit, between(event_day, 1, 9)) %>%
  group_by(unit) %>% summarise(n_valid_no_close = sum(is.finite(amihud)),
    raw_no_close = finite_mean(amihud), .groups = "drop")
no_close_qa <- s %>% filter(phase == "AP") %>%
  select(unit, matched_group_id, stock_id, review_id) %>% left_join(ap_without_close, by = "unit") %>%
  mutate(n_valid_no_close = coalesce(n_valid_no_close, 0L), expected_days = 9L,
    required_days = ceiling(MIN_WINDOW_COVERAGE * expected_days),
    eligible = n_valid_no_close >= required_days & is.finite(raw_no_close) & raw_no_close > 0)
write_out(no_close_qa, "exclude_rebalance_coverage.csv")
if (all(no_close_qa$eligible)) {
  no_close_data <- s
  ap_rows <- no_close_data$phase == "AP"
  no_close_data$raw[ap_rows] <- no_close_qa$raw_no_close[match(no_close_data$unit[ap_rows], no_close_qa$unit)]
  no_close_data$ln <- log(no_close_data$raw)
  no_close <- fit_model(no_close_data, "ln", TRUE, TRUE)
  additional_models$exclude_rebalance <- no_close
  write_out(no_close$aggregate, "exclude_rebalance_effects.csv")
  reversion_checks$no_close <- mutate(contrast_results(no_close), specification = "Exclude rebalance day", groups = no_close$groups)
  robust_effects$no_close <- mutate(no_close$aggregate, specification = "Exclude rebalance day", groups = no_close$groups)
} else {
  warning("Rebalance exclusion skipped: the fixed main sample does not pass the nine-day AP requirement. See exclude_rebalance_coverage.csv. No silent sample change was made.")
}
reversion_robustness <- bind_rows(reversion_checks)
robustness_long <- bind_rows(robust_effects)
write_out(reversion_robustness, "reversion_robustness.csv")
write_out(robustness_long, "robustness_stage_effects.csv")

# Re-estimate and reweight after omitting each review. Use each fitted model's
# complete covariance for LP-AP, SP-AP and LP-SP, rather than separate-stage SEs.
if (RUN_LEAVE_ONE_REVIEW_OUT) {
  reversion_loo <- bind_rows(lapply(revs, function(r) {
    f <- fit_model(filter(s, review_id != r), "ln", TRUE, TRUE)
    mutate(contrast_results(f), omitted = r, groups = f$groups)
  }))
  write_out(reversion_loo, "reversion_leave_one_review_out.csv")
}

# Complementary outcomes. Shares outstanding are in shares, not thousands.
# Daily turnover is percentage points: 100 * share volume / shares outstanding.
# Logs are applied AFTER arithmetic stage averaging, as with the Amihud outcome.
# A zero-volume observation stays invalid under the report's existing rule.
write_out(fits$raw_het_X$aggregate, "raw_amihud_effects.csv")
turnover_available <- "shares_outstanding" %in% names(d)
turnover_daily <- d %>% filter(unit %in% s$unit)
turnover_daily$daily_value_aud <- ifelse(turnover_daily$valid_trade,
  turnover_daily$close * turnover_daily$volume, NA_real_)
if (turnover_available) {
  turnover_daily$shares_outstanding <- suppressWarnings(as.numeric(turnover_daily$shares_outstanding))
  turnover_daily$turnover_pct <- ifelse(turnover_daily$valid_trade &
    is.finite(turnover_daily$shares_outstanding) & turnover_daily$shares_outstanding > 0,
    100 * turnover_daily$volume / turnover_daily$shares_outstanding, NA_real_)
  tv <- turnover_daily %>% group_by(unit, phase) %>%
    summarise(n_turnover = sum(is.finite(turnover_pct)),
      mean_turnover_pct = finite_mean(turnover_pct), .groups = "drop")
  tz <- s %>% left_join(tv, by = c("unit", "phase")) %>%
    mutate(turnover_eligible = coalesce(n_turnover, 0L) >= ceiling(MIN_WINDOW_COVERAGE * n_days) &
      is.finite(mean_turnover_pct) & mean_turnover_pct > 0)
  write_out(tz %>% select(unit, review_id, matched_group_id, phase, n_days, n_turnover,
    mean_turnover_pct, turnover_eligible), "turnover_coverage.csv")
  write_out(data.frame(daily_rows = nrow(turnover_daily),
    valid_turnover_days = sum(is.finite(turnover_daily$turnover_pct)),
    share_counts = n_distinct(turnover_daily$shares_outstanding),
    max_share_counts_per_stock_review = max(tapply(turnover_daily$shares_outstanding,
      turnover_daily$unit, function(x) n_distinct(x)))), "turnover_audit.csv")
  if (all(tz$turnover_eligible)) {
    tz$raw <- tz$mean_turnover_pct
    turnover_level <- fit_model(tz, "raw", TRUE, TRUE)
    tz$ln <- log(tz$mean_turnover_pct)
    turnover_log <- fit_model(tz, "ln", TRUE, TRUE)
    write_out(turnover_level$aggregate, "turnover_pct_effects.csv")
    write_out(turnover_log$aggregate, "log_turnover_effects.csv")
    additional_models$turnover_level <- turnover_level
    additional_models$turnover_log <- turnover_log
  } else warning("Turnover regressions skipped: shares or coverage fail on the fixed main sample. See turnover_coverage.csv; no values were filled.")
} else {
  turnover_daily$turnover_pct <- NA_real_
  warning("No shares_outstanding column: turnover checks skipped. Amihud analyses remain available.")
}

# Baseline characteristics: equal stock-review means. The matched-group FE
# difference has ticker-clustered CR1 inference, allowing ticker reuse.
baseline_daily <- turnover_daily %>% filter(phase == "B") %>% group_by(unit) %>%
  summarise(mean_value_aud = finite_mean(daily_value_aud),
    mean_turnover_pct = finite_mean(turnover_pct), .groups = "drop")
baseline_data <- s %>% filter(phase == "B") %>% left_join(baseline_daily, by = "unit")
baseline_stat <- function(column, label, divisor = 1) {
  z <- baseline_data
  y <- z[[column]] / divisor
  if (any(!is.finite(y))) return(data.frame(variable = label, addition_mean = NA_real_,
    control_mean = NA_real_, difference = NA_real_, se = NA_real_, p = NA_real_))
  X <- model.matrix(~ factor(matched_group_id) + treatment, z)
  fit <- lm.wfit(X, y, z$w)
  stopifnot(fit$rank == ncol(X))
  H <- solve(crossprod(X, z$w * X))
  scores <- rowsum(X * as.numeric(z$w * fit$residuals), z$stock_id, reorder = FALSE)
  G <- n_distinct(z$stock_id); N <- nrow(z); K <- ncol(X)
  V <- H %*% crossprod(scores) %*% H * G/(G-1) * (N-1)/(N-K)
  j <- match("treatment", colnames(X)); b <- fit$coefficients[j]; se <- sqrt(V[j,j])
  data.frame(variable = label, addition_mean = mean(y[z$treatment == 1]),
    control_mean = mean(y[z$treatment == 0]), difference = b, se = se,
    p = 2 * pt(-abs(b/se), G-1))
}
baseline_summary <- bind_rows(
  baseline_stat("reference_market_cap_aud", "Reference-date market cap (A$m)", 1e6),
  baseline_stat("cap_B", "Baseline mean market cap (A$m)", 1e6),
  baseline_stat("raw", "Mean daily Amihud (scaled by 1e6)"),
  baseline_stat("mean_value_aud", "Mean daily traded value (A$m)", 1e6),
  baseline_stat("mean_turnover_pct", "Mean daily turnover (%)"),
  baseline_stat("ln", "Log mean daily Amihud"))
write_out(baseline_summary, "baseline_characteristics.csv")

# Report-ready exports retain both nominal and Holm-adjusted p-values.
# Contrast percentages use exp(beta_later - beta_earlier)-1, not percentage-point
# subtraction of two exp(beta)-1 estimates. Do not divide raw effects by a
# baseline mean and present the result as the log-model effect.
write_out(main$aggregate, "report_table_5_main_effects.csv")
write_out(contrast_results(main), "report_table_6_contrasts.csv")
table7 <- robustness_long %>% filter(term %in% c("AP", "SP", "LP")) %>%
  select(specification, term, effect_pct, p, p_holm, groups) %>%
  tidyr::pivot_wider(names_from = term, values_from = c(effect_pct, p, p_holm)) %>%
  left_join(reversion_robustness %>% filter(contrast == "LP - AP") %>%
    transmute(specification, LP_minus_AP_pct = effect_pct,
      LP_minus_AP_p = p, LP_minus_AP_p_holm = p_holm), by = "specification")
write_out(table7, "report_table_7_robustness.csv")
table8 <- list(raw_amihud = mutate(fits$raw_het_X$aggregate,
  outcome = "Raw mean Amihud", units = "absolute change in scaled ratio"))
if (exists("turnover_level")) {
  table8$turnover_pct <- mutate(turnover_level$aggregate,
    outcome = "Mean turnover", units = "percentage points")
  table8$log_turnover <- mutate(turnover_log$aggregate,
    outcome = "Log mean turnover", units = "log; exponentiated effect also reported")
}
write_out(bind_rows(table8), "report_table_8_complementary_outcomes.csv")
saveRDS(additional_models, file.path(od, "additional_fitted_models.rds"))

# Regenerate the four report figures with sequential review legends and enough
# top/left padding to keep the y-axis labels visible. B is explicitly normalised
# to zero; no line or confidence interval is estimated for the omitted B effect.
report_theme <- theme_minimal(base_size = 10, base_family = "Arial") +
  theme(panel.grid.minor = element_blank(), legend.position = "bottom",
    plot.margin = margin(10, 12, 6, 12),
    axis.title.y = element_text(margin = margin(r = 9)))
save_report_plot <- function(name, plot, height = 2.1) {
  ggsave(file.path(fig_dir, paste0(name, ".png")), plot,
    width = 6.5, height = height, dpi = 300, bg = "white")
}
rv <- filter(coef_table, model == "ln_het_X")
rv <- bind_rows(rv, expand.grid(review_id = revs, phase = "B") %>% mutate(beta = 0))
rv$phase <- factor(rv$phase, levels = ph)
ylimits <- c(min(-.9, min(rv$beta) - .1), max(.65, max(rv$beta) + .12))
g_review <- ggplot(rv, aes(phase, beta, color = review_id, group = review_id)) +
  geom_hline(yintercept = 0, color = "grey65", linetype = 2) +
  geom_line(linewidth = .55) + geom_point(size = 1.3) +
  scale_color_manual(values = c("#1B6F82", "#C37C25", "#72549A", "#2F8B69", "#C24F63", "#4C79B9")) +
  scale_y_continuous(breaks = c(-.5, 0, .5), limits = ylimits,
    expand = expansion(mult = c(.03, .05))) +
  guides(color = guide_legend(nrow = 2, byrow = TRUE)) +
  labs(x = "Stage (B = 0)", y = "Log coefficient", color = NULL) + report_theme
save_report_plot("report_figure_3_review_paths", g_review)
ma <- main$aggregate %>% transmute(phase = term, effect_pct, lo_pct, hi_pct)
ma <- bind_rows(ma, data.frame(phase = "B", effect_pct = 0, lo_pct = NA, hi_pct = NA))
ma$phase <- factor(ma$phase, levels = ph)
save_report_plot("report_figure_2_main", ggplot(ma, aes(phase, effect_pct)) +
  geom_hline(yintercept = 0, color = "grey55", linetype = 2) +
  geom_errorbar(aes(ymin = lo_pct, ymax = hi_pct), width = .10, color = "#155B6A", na.rm = TRUE) +
  geom_point(size = 2.2, color = "#155B6A") +
  labs(x = "Stage (B is the omitted reference)", y = "Relative effect (%)") + report_theme)
report_pre <- filter(prec, model == "heterogeneous")
report_pre <- bind_rows(report_pre,
  data.frame(term = "P3", beta = 0, se = 0, lo = NA, hi = NA, p = NA,
    p_holm = NA, effect_pct = 0, lo_pct = NA, hi_pct = NA, model = "heterogeneous"))
report_pre$term <- factor(report_pre$term, levels = paste0("P", 1:4))
save_report_plot("report_figure_1_pretrend", ggplot(report_pre, aes(term, beta)) +
  geom_hline(yintercept = 0, color = "grey55", linetype = 2) +
  geom_errorbar(aes(ymin = lo, ymax = hi), width = .10, color = "#155B6A", na.rm = TRUE) +
  geom_point(size = 2, color = "#155B6A") +
  scale_x_discrete(labels = c("-60:-51", "-50:-41", "-40:-31", "-30:-21")) +
  labs(x = "Trading-day bin (reference -40:-31)", y = "Change in log gap") + report_theme, 1.85)
if (nrow(loo)) {
  rl <- filter(loo, term %in% c("AP", "SP", "LP"))
  rl$term <- factor(rl$term, levels = c("AP", "SP", "LP"))
  save_report_plot("report_figure_4_leave_one_out", ggplot(rl, aes(omitted, effect_pct)) +
    geom_hline(yintercept = 0, color = "grey60", linetype = 2) +
    geom_errorbar(aes(ymin = lo_pct, ymax = hi_pct), width = .12, color = "#155B6A") +
    geom_point(color = "#155B6A", size = 1.5) + facet_wrap(~term, nrow = 1) +
    labs(x = "Review omitted", y = "Relative effect (%)") + report_theme +
    theme(axis.text.x = element_text(size = 8)), 2.0)
}
message("Report checks complete. See report_table_7_robustness.csv, report_table_8_complementary_outcomes.csv and baseline_characteristics.csv.")


write_out(data.frame(file=basename(files),md5=unname(tools::md5sum(files))), 'input_file_fingerprints.csv')
writeLines(capture.output(sessionInfo()),file.path(log_dir,'R_session_info.txt'))
writeLines(c(paste('Main cap:',CAP_SPEC),paste('Baseline: -40:-21; volatility: -60:-41'),
  paste('Groups:',main$groups,'; ticker clusters:',main$clusters,'; window rows:',main$N,'; full rank:',main$rank),
  'Main Y = log(mean daily Amihud within window). No filling. Zero volume invalid.',
  'Whole matched groups excluded if any required window/covariate is invalid; see QA files.',
  'WLS observation weights: treated 1, each control 0.5; aggregation weights: addition counts.',
  'Ticker-clustered CR1; t/F degrees of freedom = number of clusters minus one.',
  'Holm families: five non-baseline window effects; separately three post-window contrasts.',
  'P99 robustness uses a fixed pooled daily pre-period cutoff (-60:-21).',
  'Strict80 sensitivity also requires 16/20 valid baseline-cap observations.',
  'Pre-trend non-rejection does not establish parallel trends or rule out anticipation.'),file.path(log_dir,'analysis_settings.txt'))
message('Finished. Main event-weighted estimates:')
print(main$aggregate)
message('Joint tests:');print(main$tests)
message('Tables saved to ',od,'; figures saved to ',fig_dir)
