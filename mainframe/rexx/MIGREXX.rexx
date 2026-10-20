/* REXX */
/*********************************************************************/
/* MIGREXX - STEP040 of job MIGVALID (run through IKJEFT01)          */
/* 1. reads ICETOOL count files and the COBOL control record         */
/* 2. reads the exception file, drops repeats, sorts by type + key   */
/* 3. cross-checks all counts, takes the APPROVE / REJECT decision   */
/* 4. writes: sorted exceptions, report, result, KSDS record, SQL    */
/* Exit code: 0 approved, 4 warning (duplicates only), 8 rejected,   */
/*            12 aborted (controls disagree), 16 REXX failure        */
/* DD names: CNTRAW CNTDED CNTTGT CTLIN EXCIN                        */
/*           EXCSORT REPORT RESULT CTLREC SQLOUT                     */
/*********************************************************************/
numeric digits 20
signal on syntax name FATAL
signal on novalue name FATAL

bid = 'B'date('S')space(translate(time('N'),' ',':'),0)
rundate = substr(date('S'),1,4)'-'substr(date('S'),5,2)'-'substr(date('S'),7,2)
runtime = time('N')

/* ---- 1. counts written by ICETOOL ------------------------------- */
raw  = GetCount('CNTRAW', 'RAW=')
ded  = GetCount('CNTDED', 'DEDUP=')
tgtc = GetCount('CNTTGT', 'TGT=')
dups = raw - ded

/* ---- 2. control record written by MIGMATCH ---------------------- */
call ReadAll 'CTLIN'
if io.0 < 1 then call Die 'CTLIN IS EMPTY'
rec = left(io.1, 120)
tag = substr(rec, 1, 8)
c_src = Num(substr(rec,  9, 10))
c_tgt = Num(substr(rec, 19, 10))
c_mat = Num(substr(rec, 29, 10))
c_mis = Num(substr(rec, 39, 10))
c_mss = Num(substr(rec, 49, 10))
c_ext = Num(substr(rec, 59, 10))
src_tot = Money(substr(rec, 69, 16))
tgt_tot = Money(substr(rec, 85, 16))
reason = strip(substr(rec, 101, 20))

/* ---- 3. exceptions: drop repeats, rank, sort -------------------- */
call ReadAll 'EXCIN'
seen. = 0
mk.   = 0
nx = 0
x_mss = 0
x_ext = 0
x_mis = 0
do i = 1 to io.0
   line = left(io.i, 100)
   if strip(line) = '' then iterate
   if seen.line = 1 then iterate
   seen.line = 1
   typ = strip(substr(line, 19, 8))
   if typ = 'MISSING' then rk = 1
   else if typ = 'MISMATCH' then rk = 2
   else if typ = 'EXTRA' then rk = 3
   else call Die 'UNKNOWN EXCEPTION TYPE' typ
   nx = nx + 1
   xl.nx = line
   xk.nx = rk'-'substr(line,1,18)'-'substr(line,27,8)
   if rk = 1 then x_mss = x_mss + 1
   if rk = 3 then x_ext = x_ext + 1
   if rk = 2 then do
      mkey = substr(line,1,18)
      if mk.mkey = 0 then do
         mk.mkey = 1
         x_mis = x_mis + 1
      end
   end
end
call ShellSort

/* ---- 4. cross-checks and decision ------------------------------- */
problem = ''
if tag <> 'MIGCTRL ' then problem = 'COBOL ABORT:' reason
else do
   if c_src <> ded then problem = 'SOURCE COUNT: SORT' ded 'COBOL' c_src
   else if c_tgt <> tgtc then problem = 'TARGET COUNT: SORT' tgtc 'COBOL' c_tgt
   else if raw < ded then problem = 'RAW COUNT LOWER THAN DEDUP COUNT'
   else if c_mat + c_mis + c_mss <> c_src then
      problem = 'MATCHED+MISMATCH+MISSING <> SOURCE COUNT'
   else if c_mat + c_mis + c_ext <> c_tgt then
      problem = 'MATCHED+MISMATCH+EXTRA <> TARGET COUNT'
   else if x_mss <> c_mss then problem = 'MISSING ROWS <> CONTROL COUNT'
   else if x_ext <> c_ext then problem = 'EXTRA ROWS <> CONTROL COUNT'
   else if x_mis <> c_mis then problem = 'MISMATCH ROWS <> CONTROL COUNT'
end

if problem <> '' then do
   finalrc = 12
   decision = 'ABORTED'
end
else if c_mss + c_ext + c_mis > 0 then do
   finalrc = 8
   decision = 'REJECTED'
end
else if dups > 0 then do
   finalrc = 4
   decision = 'WARNING'
end
else do
   finalrc = 0
   decision = 'APPROVED'
end

/* ---- 5. sorted exception dataset -------------------------------- */
do i = 1 to nx
   out.i = xl.i
end
out.0 = nx
call WriteAll 'EXCSORT'

/* ---- 6. report -------------------------------------------------- */
rpn = 0
call Put '1MIGRATION VALIDATION REPORT'
call Put ' Legacy-to-Modern Data Migration Validator'
call Put ' '
call Put ' BATCH ID  :' bid
call Put ' RUN DATE  :' rundate runtime
if decision = 'APPROVED' then msg = 'SAFE TO CUT OVER'
if decision = 'WARNING'  then msg = 'SAFE TO CUT OVER - DUPLICATES WERE REMOVED'
if decision = 'REJECTED' then msg = 'DO NOT CUT OVER'
if decision = 'ABORTED'  then msg = 'HOLD - CONTROLS DISAGREE OR INPUT INVALID'
call Put ' DECISION  :' decision '(RC' finalrc')  'msg
if problem <> '' then call Put ' REASON    :' problem
call Put ' '
call Put '0RECONCILIATION'
call Put '   Source raw records ............' right(Comma(raw),10)
call Put '   Duplicates removed (DFSORT) ...' right(Comma(dups),10)
call Put '   Unique source records .........' right(Comma(ded),10)
call Put '   Target records ................' right(Comma(tgtc),10)
call Put '   Matched .......................' right(Comma(c_mat),10)
call Put '   Mismatched records ............' right(Comma(c_mis),10)
call Put '   Missing in target .............' right(Comma(c_mss),10)
call Put '   Extra in target ...............' right(Comma(c_ext),10)
if c_mat + c_mis + c_mss = c_src then ok1 = 'OK'
else ok1 = 'FAILED'
if c_mat + c_mis + c_ext = c_tgt then ok2 = 'OK'
else ok2 = 'FAILED'
call Put ' '
call Put '   Check: matched + mismatched + missing = unique source :' ok1
call Put '   Check: matched + mismatched + extra   = target        :' ok2
call Put ' '
call Put '0BALANCE CONTROL TOTALS (information only)'
call Put '   Source total ...' right(format(src_tot,,2),18)
call Put '   Target total ...' right(format(tgt_tot,,2),18)
call Put '   Difference .....' right(format(tgt_tot - src_tot,,2),18)
call Put ' '
call Put '0EXCEPTIONS SORTED BY TYPE AND KEY ('nx 'rows)'
call Put ' '
hdr = ' 'left('TYPE',9)left('CUST-ID',9)left('ACCT-NO',11)
hdr = hdr''left('FIELD',9)left('SOURCE VALUE',31)'TARGET VALUE'
call Put hdr
do i = 1 to nx
   l = xl.i
   dl = ' 'left(substr(l,19,8),9)left(substr(l,1,8),9)
   dl = dl''left(substr(l,9,10),11)left(substr(l,27,8),9)
   dl = dl''left(substr(l,35,30),31)substr(l,65,30)
   call Put dl
end
call Put ' '
call Put ' *** END OF REPORT ***'
do i = 1 to rpn
   out.i = left(rp.i, 133)
end
out.0 = rpn
call WriteAll 'REPORT'

/* ---- 7. result dataset (key=value, read by the Python UI) ------- */
out.1  = left('BATCH_ID='bid, 80)
out.2  = left('DECISION='decision, 80)
out.3  = left('RC='finalrc, 80)
out.4  = left('SRC_RAW='raw, 80)
out.5  = left('DUPS='dups, 80)
out.6  = left('SRC_UNIQUE='ded, 80)
out.7  = left('TGT_CNT='tgtc, 80)
out.8  = left('MATCHED='c_mat, 80)
out.9  = left('MISMATCH='c_mis, 80)
out.10 = left('MISSING='c_mss, 80)
out.11 = left('EXTRA='c_ext, 80)
out.12 = left('SRC_BAL_TOT='format(src_tot,,2), 80)
out.13 = left('TGT_BAL_TOT='format(tgt_tot,,2), 80)
out.14 = left('REASON='problem, 80)
out.15 = left('RUN_DATE='rundate runtime, 80)
out.0  = 15
call WriteAll 'RESULT'

/* ---- 8. KSDS record: key = batch id (15 bytes) ------------------ */
kr = left(bid, 15)left(decision, 10)right(finalrc, 3, '0')
kr = kr''right(raw,10,'0')right(dups,10,'0')right(ded,10,'0')
kr = kr''right(tgtc,10,'0')right(c_mat,10,'0')right(c_mis,10,'0')
kr = kr''right(c_mss,10,'0')right(c_ext,10,'0')
out.1 = left(kr, 120)
out.0 = 1
call WriteAll 'CTLREC'

/* ---- 9. SQL for the DB2 audit tables (run by DSNTEP2) ----------- */
sqn = 0
call Sql 'INSERT INTO MIG_BATCH_LOG'
call Sql ' (BATCH_ID, SRC_RAW, DUPS, SRC_UNIQUE, TGT_CNT,'
call Sql '  MATCHED, MISMATCH, MISSING, EXTRA, RC, DECISION,'
call Sql '  SRC_BAL_TOT, TGT_BAL_TOT)'
call Sql " VALUES ('"bid"',"raw","dups","ded","tgtc","
call Sql '  'c_mat','c_mis','c_mss','c_ext','finalrc','
call Sql "  '"decision"',"
call Sql '  'format(src_tot,,2)','format(tgt_tot,,2)');'
do i = 1 to nx
   l = xl.i
   call Sql 'INSERT INTO MIG_EXCEPTION'
   call Sql ' (BATCH_ID, CUST_ID, ACCT_NO,'
   call Sql '  ERR_TYPE, FIELD_NAME, SRC_VAL, TGT_VAL)'
   call Sql " VALUES ('"bid"', '"Esc(strip(substr(l,1,8)))"',"
   call Sql "  '"Esc(strip(substr(l,9,10)))"', '"strip(substr(l,19,8))"',"
   call Sql "  '"strip(substr(l,27,8))"',"
   call Sql "  '"Esc(strip(substr(l,35,30)))"',"
   call Sql "  '"Esc(strip(substr(l,65,30)))"');"
end
call Sql 'COMMIT;'
do i = 1 to sqn
   out.i = left(sq.i, 80)
end
out.0 = sqn
call WriteAll 'SQLOUT'

say 'MIGREXX BATCH' bid 'DECISION' decision 'RC' finalrc
exit finalrc

/* ================================================================= */
/* helpers                                                           */
/* ================================================================= */
Put:
   rpn = rpn + 1
   rp.rpn = arg(1)
   return

Sql:
   if length(arg(1)) > 72 then call Die 'SQL LINE TOO LONG:' arg(1)
   sqn = sqn + 1
   sq.sqn = arg(1)
   return

ShellSort:
   gap = nx % 2
   do while gap > 0
      do si = gap + 1 to nx
         tk = xk.si
         tl = xl.si
         sj = si
         do while sj > gap
            sp = sj - gap
            if xk.sp >> tk then do
               xk.sj = xk.sp
               xl.sj = xl.sp
               sj = sp
            end
            else leave
         end
         xk.sj = tk
         xl.sj = tl
      end
      gap = gap % 2
   end
   return

GetCount: procedure expose io.
   parse arg dd, pfx
   call ReadAll dd
   do k = 1 to io.0
      t = strip(io.k)
      if left(t, length(pfx)) = pfx then
         return Num(word(substr(t, length(pfx) + 1), 1))
   end
   call Die 'NO' pfx 'LINE IN' dd
   return 0

Num: procedure
   parse arg s
   s = strip(s)
   if s = '' then call Die 'EMPTY NUMBER'
   if datatype(s, 'W') = 0 then call Die 'BAD NUMBER' s
   return s + 0

Money: procedure
   parse arg s
   sgn = left(s, 1)
   digs = substr(s, 2)
   if sgn <> '+' & sgn <> '-' then call Die 'BAD SIGN IN TOTAL' s
   if datatype(digs, 'W') = 0 then call Die 'BAD TOTAL' s
   v = digs / 100
   if sgn = '-' then v = -v
   return v

Comma: procedure
   parse arg n
   s = strip(n)
   o = ''
   do while length(s) > 3
      o = ','right(s, 3)o
      s = left(s, length(s) - 3)
   end
   return s''o

Esc: procedure
   parse arg s
   o = ''
   do k = 1 to length(s)
      ch = substr(s, k, 1)
      if ch = "'" then o = o"''"
      else o = o''ch
   end
   return o

Die:
   say 'MIGREXX ERROR:' arg(1)
   exit 16

FATAL:
   say 'MIGREXX FAILED AT LINE' sigl':' strip(sourceline(sigl))
   say 'CONDITION' condition('C') condition('D')
   exit 16

/* ==IO-BEGIN== (the unit tests replace everything down to IO-END) */
ReadAll:
   parse arg zzdd
   io.0 = 0
   "EXECIO * DISKR" zzdd "(STEM io. FINIS"
   if rc <> 0 & rc <> 2 then call Die 'EXECIO READ RC' rc 'DD' zzdd
   return

WriteAll:
   parse arg zzdd
   "EXECIO" out.0 "DISKW" zzdd "(STEM out. FINIS"
   if rc <> 0 then call Die 'EXECIO WRITE RC' rc 'DD' zzdd
   return
/* ==IO-END== */
