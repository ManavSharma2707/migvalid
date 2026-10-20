       IDENTIFICATION DIVISION.
       PROGRAM-ID. MIGMATCH.
      *****************************************************************
      * MIGMATCH - STEP030 of job MIGVALID
      * Match-merge of the de-duplicated SOURCE extract (SRCIN) against
      * the sorted TARGET extract (TGTIN), both ascending by the 18 byte
      * key CUST-ID + ACCT-NO.
      *   SRCIN  FB 80   legacy layout   (DFSORT output)
      *   TGTIN  FB 100  modern layout   (DFSORT output)
      *   EXCOUT FB 100  one row per exception
      *   CTLOUT FB 120  one control record (counts and balance totals)
      * Exception types: MISSING (in source only), EXTRA (in target
      * only), MISMATCH (key on both sides, one row per differing field)
      * Return code: 0 = finished, 12 = aborted (see CTL-REASON)
      *****************************************************************
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SRC-FILE ASSIGN TO SRCIN
               FILE STATUS IS WS-FS-SRC.
           SELECT TGT-FILE ASSIGN TO TGTIN
               FILE STATUS IS WS-FS-TGT.
           SELECT EXC-FILE ASSIGN TO EXCOUT
               FILE STATUS IS WS-FS-EXC.
           SELECT CTL-FILE ASSIGN TO CTLOUT
               FILE STATUS IS WS-FS-CTL.

       DATA DIVISION.
       FILE SECTION.
       FD  SRC-FILE
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  SRC-REC.
           05  SRC-KEY.
               10  SRC-CUST-ID         PIC X(8).
               10  SRC-ACCT-NO         PIC X(10).
           05  SRC-NAME                PIC X(20).
           05  SRC-BAL                 PIC 9(9)V99.
           05  SRC-BAL-X REDEFINES SRC-BAL
                                       PIC X(11).
           05  SRC-DATE                PIC X(8).
           05  SRC-STATUS              PIC X(1).
           05  FILLER                  PIC X(22).

       FD  TGT-FILE
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  TGT-REC.
           05  TGT-KEY.
               10  TGT-CUST-ID         PIC X(8).
               10  TGT-ACCT-NO         PIC X(10).
           05  TGT-NAME                PIC X(40).
           05  TGT-BAL-TXT             PIC X(12).
           05  TGT-DATE-TXT            PIC X(10).
           05  TGT-STATUS              PIC X(1).
           05  FILLER                  PIC X(19).

       FD  EXC-FILE
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  EXC-REC.
           05  EXC-CUST-ID             PIC X(8).
           05  EXC-ACCT-NO             PIC X(10).
           05  EXC-TYPE                PIC X(8).
           05  EXC-FIELD               PIC X(8).
           05  EXC-SRC-VAL             PIC X(30).
           05  EXC-TGT-VAL             PIC X(30).
           05  FILLER                  PIC X(6).

       FD  CTL-FILE
           RECORDING MODE IS F
           BLOCK CONTAINS 0 RECORDS.
       01  CTL-REC.
           05  CTL-TAG                 PIC X(8).
           05  CTL-SRC-CNT             PIC 9(10).
           05  CTL-TGT-CNT             PIC 9(10).
           05  CTL-MATCHED             PIC 9(10).
           05  CTL-MISMATCH            PIC 9(10).
           05  CTL-MISSING             PIC 9(10).
           05  CTL-EXTRA               PIC 9(10).
           05  CTL-SRC-TOT             PIC S9(13)V99
                                       SIGN IS LEADING SEPARATE.
           05  CTL-TGT-TOT             PIC S9(13)V99
                                       SIGN IS LEADING SEPARATE.
           05  CTL-REASON              PIC X(20).

       WORKING-STORAGE SECTION.
       01  WS-FILE-STATUS.
           05  WS-FS-SRC               PIC XX VALUE SPACES.
           05  WS-FS-TGT               PIC XX VALUE SPACES.
           05  WS-FS-EXC               PIC XX VALUE SPACES.
           05  WS-FS-CTL               PIC XX VALUE SPACES.

       01  WS-SWITCHES.
           05  WS-ABORT-SW             PIC X VALUE 'N'.
               88  ABORTED             VALUE 'Y'.
           05  WS-DIFF-SW              PIC X VALUE 'N'.
               88  HAS-DIFF            VALUE 'Y'.
           05  WS-TGT-BAL-OK           PIC X VALUE 'N'.
               88  TGT-BAL-VALID       VALUE 'Y'.
           05  WS-TGT-DATE-OK          PIC X VALUE 'N'.
               88  TGT-DATE-VALID      VALUE 'Y'.

       01  WS-REASONS.
           05  WS-REASON               PIC X(20) VALUE SPACES.
           05  WS-NEW-REASON           PIC X(20) VALUE SPACES.

       01  WS-KEYS.
           05  WS-SRC-KEY              PIC X(18) VALUE LOW-VALUES.
           05  WS-TGT-KEY              PIC X(18) VALUE LOW-VALUES.
           05  WS-PREV-SRC-KEY         PIC X(18) VALUE LOW-VALUES.
           05  WS-PREV-TGT-KEY         PIC X(18) VALUE LOW-VALUES.

       01  WS-COUNTERS.
           05  WS-SRC-CNT              PIC 9(10) VALUE 0.
           05  WS-TGT-CNT              PIC 9(10) VALUE 0.
           05  WS-MATCHED-CNT          PIC 9(10) VALUE 0.
           05  WS-MISMATCH-CNT         PIC 9(10) VALUE 0.
           05  WS-MISSING-CNT          PIC 9(10) VALUE 0.
           05  WS-EXTRA-CNT            PIC 9(10) VALUE 0.
           05  WS-EXC-CNT              PIC 9(10) VALUE 0.

       01  WS-TOTALS.
           05  WS-SRC-TOT              PIC S9(13)V99 VALUE 0.
           05  WS-TGT-TOT              PIC S9(13)V99 VALUE 0.

       01  WS-WORK.
           05  WS-TGT-BAL-NUM          PIC S9(9)V99 VALUE 0.
           05  WS-TGT-DATE-N           PIC X(8) VALUE SPACES.
           05  WS-EDIT-BAL             PIC Z(8)9.99.
           05  WS-EDIT-BAL2            PIC Z(8)9.99.

       01  WS-EXC-STAGE.
           05  WS-X-CUST               PIC X(8).
           05  WS-X-ACCT               PIC X(10).
           05  WS-X-TYPE               PIC X(8).
           05  WS-X-FIELD              PIC X(8).
           05  WS-X-SRC                PIC X(30).
           05  WS-X-TGT                PIC X(30).

       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-OPEN-FILES
           IF NOT ABORTED
               PERFORM 2000-READ-SRC
               PERFORM 2100-READ-TGT
               PERFORM 3000-MATCH-MERGE
                   UNTIL ABORTED
                      OR (WS-SRC-KEY = HIGH-VALUES
                          AND WS-TGT-KEY = HIGH-VALUES)
           END-IF
           PERFORM 8000-WRITE-CONTROL
           PERFORM 9000-CLOSE-FILES
           PERFORM 8500-DISPLAY-SUMMARY
           IF ABORTED
               MOVE 12 TO RETURN-CODE
           ELSE
               MOVE 0 TO RETURN-CODE
           END-IF
           GOBACK.

       1000-OPEN-FILES.
           OPEN INPUT SRC-FILE
           IF WS-FS-SRC NOT = '00'
               MOVE 'SRCIN OPEN ERROR' TO WS-NEW-REASON
               PERFORM 9900-ABORT
           END-IF
           OPEN INPUT TGT-FILE
           IF WS-FS-TGT NOT = '00'
               MOVE 'TGTIN OPEN ERROR' TO WS-NEW-REASON
               PERFORM 9900-ABORT
           END-IF
           OPEN OUTPUT EXC-FILE
           IF WS-FS-EXC NOT = '00'
               MOVE 'EXCOUT OPEN ERROR' TO WS-NEW-REASON
               PERFORM 9900-ABORT
           END-IF
           OPEN OUTPUT CTL-FILE
           IF WS-FS-CTL NOT = '00'
               MOVE 'CTLOUT OPEN ERROR' TO WS-NEW-REASON
               PERFORM 9900-ABORT
           END-IF.

      * Read next source record; at end the key becomes HIGH-VALUES
       2000-READ-SRC.
           IF NOT ABORTED
               READ SRC-FILE
                   AT END
                       MOVE HIGH-VALUES TO WS-SRC-KEY
                   NOT AT END
                       PERFORM 2010-CHECK-SRC
               END-READ
               IF WS-FS-SRC NOT = '00' AND WS-FS-SRC NOT = '10'
                   MOVE 'SRCIN READ ERROR' TO WS-NEW-REASON
                   PERFORM 9900-ABORT
               END-IF
           END-IF.

       2010-CHECK-SRC.
           ADD 1 TO WS-SRC-CNT
           MOVE SRC-KEY TO WS-SRC-KEY
           IF SRC-BAL IS NUMERIC
               ADD SRC-BAL TO WS-SRC-TOT
           END-IF
           IF WS-SRC-KEY <= WS-PREV-SRC-KEY
               MOVE 'SRC SEQUENCE ERROR' TO WS-NEW-REASON
               PERFORM 9900-ABORT
           ELSE
               MOVE WS-SRC-KEY TO WS-PREV-SRC-KEY
           END-IF.

      * Read next target record and normalise balance and date
       2100-READ-TGT.
           IF NOT ABORTED
               READ TGT-FILE
                   AT END
                       MOVE HIGH-VALUES TO WS-TGT-KEY
                   NOT AT END
                       PERFORM 2110-CHECK-TGT
               END-READ
               IF WS-FS-TGT NOT = '00' AND WS-FS-TGT NOT = '10'
                   MOVE 'TGTIN READ ERROR' TO WS-NEW-REASON
                   PERFORM 9900-ABORT
               END-IF
           END-IF.

       2110-CHECK-TGT.
           ADD 1 TO WS-TGT-CNT
           MOVE TGT-KEY TO WS-TGT-KEY
           IF WS-TGT-KEY = WS-PREV-TGT-KEY
               MOVE 'TGT DUPLICATE KEY' TO WS-NEW-REASON
               PERFORM 9900-ABORT
           ELSE
               IF WS-TGT-KEY < WS-PREV-TGT-KEY
                   MOVE 'TGT SEQUENCE ERROR' TO WS-NEW-REASON
                   PERFORM 9900-ABORT
               ELSE
                   MOVE WS-TGT-KEY TO WS-PREV-TGT-KEY
               END-IF
           END-IF
           PERFORM 2120-NORMALISE-TGT.

       2120-NORMALISE-TGT.
           MOVE 'N' TO WS-TGT-BAL-OK
           MOVE 0 TO WS-TGT-BAL-NUM
           IF FUNCTION TEST-NUMVAL(TGT-BAL-TXT) = 0
               MOVE 'Y' TO WS-TGT-BAL-OK
               COMPUTE WS-TGT-BAL-NUM = FUNCTION NUMVAL(TGT-BAL-TXT)
                   ON SIZE ERROR
                       MOVE 'N' TO WS-TGT-BAL-OK
               END-COMPUTE
           END-IF
           IF TGT-BAL-VALID
               ADD WS-TGT-BAL-NUM TO WS-TGT-TOT
           END-IF
           MOVE 'N' TO WS-TGT-DATE-OK
           MOVE SPACES TO WS-TGT-DATE-N
           IF TGT-DATE-TXT(5:1) = '-' AND TGT-DATE-TXT(8:1) = '-'
               MOVE TGT-DATE-TXT(1:4) TO WS-TGT-DATE-N(1:4)
               MOVE TGT-DATE-TXT(6:2) TO WS-TGT-DATE-N(5:2)
               MOVE TGT-DATE-TXT(9:2) TO WS-TGT-DATE-N(7:2)
               MOVE 'Y' TO WS-TGT-DATE-OK
           END-IF.

       3000-MATCH-MERGE.
           EVALUATE TRUE
               WHEN WS-SRC-KEY < WS-TGT-KEY
                   PERFORM 4000-MISSING
                   PERFORM 2000-READ-SRC
               WHEN WS-SRC-KEY > WS-TGT-KEY
                   PERFORM 4100-EXTRA
                   PERFORM 2100-READ-TGT
               WHEN OTHER
                   PERFORM 5000-COMPARE
                   PERFORM 2000-READ-SRC
                   PERFORM 2100-READ-TGT
           END-EVALUATE.

      * Key only in source
       4000-MISSING.
           ADD 1 TO WS-MISSING-CNT
           MOVE SRC-CUST-ID TO WS-X-CUST
           MOVE SRC-ACCT-NO TO WS-X-ACCT
           MOVE 'MISSING' TO WS-X-TYPE
           MOVE '*RECORD' TO WS-X-FIELD
           MOVE SPACES TO WS-X-SRC WS-X-TGT
           IF SRC-BAL IS NUMERIC
               MOVE SRC-BAL TO WS-EDIT-BAL
               STRING FUNCTION TRIM(SRC-NAME) DELIMITED BY SIZE
                      ' ' DELIMITED BY SIZE
                      FUNCTION TRIM(WS-EDIT-BAL) DELIMITED BY SIZE
                      INTO WS-X-SRC
                   ON OVERFLOW CONTINUE
               END-STRING
           ELSE
               MOVE SRC-NAME TO WS-X-SRC
           END-IF
           PERFORM 6000-WRITE-EXC.

      * Key only in target
       4100-EXTRA.
           ADD 1 TO WS-EXTRA-CNT
           MOVE TGT-CUST-ID TO WS-X-CUST
           MOVE TGT-ACCT-NO TO WS-X-ACCT
           MOVE 'EXTRA' TO WS-X-TYPE
           MOVE '*RECORD' TO WS-X-FIELD
           MOVE SPACES TO WS-X-SRC WS-X-TGT
           IF TGT-BAL-VALID
               MOVE WS-TGT-BAL-NUM TO WS-EDIT-BAL
               STRING FUNCTION TRIM(TGT-NAME) DELIMITED BY SIZE
                      ' ' DELIMITED BY SIZE
                      FUNCTION TRIM(WS-EDIT-BAL) DELIMITED BY SIZE
                      INTO WS-X-TGT
                   ON OVERFLOW CONTINUE
               END-STRING
           ELSE
               MOVE TGT-NAME TO WS-X-TGT
           END-IF
           PERFORM 6000-WRITE-EXC.

      * Same key on both sides: compare field by field
       5000-COMPARE.
           MOVE 'N' TO WS-DIFF-SW
           MOVE SRC-CUST-ID TO WS-X-CUST
           MOVE SRC-ACCT-NO TO WS-X-ACCT
           MOVE 'MISMATCH' TO WS-X-TYPE

           IF SRC-NAME NOT = TGT-NAME
               MOVE 'NAME' TO WS-X-FIELD
               MOVE SPACES TO WS-X-SRC WS-X-TGT
               MOVE SRC-NAME TO WS-X-SRC
               MOVE TGT-NAME(1:30) TO WS-X-TGT
               PERFORM 5900-FLAG-DIFF
           END-IF

           IF SRC-BAL IS NOT NUMERIC OR NOT TGT-BAL-VALID
               MOVE 'BALANCE' TO WS-X-FIELD
               MOVE SPACES TO WS-X-SRC WS-X-TGT
               MOVE SRC-BAL-X TO WS-X-SRC
               MOVE TGT-BAL-TXT TO WS-X-TGT
               PERFORM 5900-FLAG-DIFF
           ELSE
               IF SRC-BAL NOT = WS-TGT-BAL-NUM
                   MOVE 'BALANCE' TO WS-X-FIELD
                   MOVE SPACES TO WS-X-SRC WS-X-TGT
                   MOVE SRC-BAL TO WS-EDIT-BAL
                   MOVE WS-TGT-BAL-NUM TO WS-EDIT-BAL2
                   MOVE FUNCTION TRIM(WS-EDIT-BAL) TO WS-X-SRC
                   MOVE FUNCTION TRIM(WS-EDIT-BAL2) TO WS-X-TGT
                   PERFORM 5900-FLAG-DIFF
               END-IF
           END-IF

           IF NOT TGT-DATE-VALID
               MOVE 'TXNDATE' TO WS-X-FIELD
               MOVE SPACES TO WS-X-SRC WS-X-TGT
               MOVE SRC-DATE TO WS-X-SRC
               MOVE TGT-DATE-TXT TO WS-X-TGT
               PERFORM 5900-FLAG-DIFF
           ELSE
               IF SRC-DATE NOT = WS-TGT-DATE-N
                   MOVE 'TXNDATE' TO WS-X-FIELD
                   MOVE SPACES TO WS-X-SRC WS-X-TGT
                   MOVE SRC-DATE TO WS-X-SRC
                   MOVE TGT-DATE-TXT TO WS-X-TGT
                   PERFORM 5900-FLAG-DIFF
               END-IF
           END-IF

           IF SRC-STATUS NOT = TGT-STATUS
               MOVE 'STATUS' TO WS-X-FIELD
               MOVE SPACES TO WS-X-SRC WS-X-TGT
               MOVE SRC-STATUS TO WS-X-SRC
               MOVE TGT-STATUS TO WS-X-TGT
               PERFORM 5900-FLAG-DIFF
           END-IF

           IF HAS-DIFF
               ADD 1 TO WS-MISMATCH-CNT
           ELSE
               ADD 1 TO WS-MATCHED-CNT
           END-IF.

       5900-FLAG-DIFF.
           MOVE 'Y' TO WS-DIFF-SW
           PERFORM 6000-WRITE-EXC.

       6000-WRITE-EXC.
           MOVE SPACES TO EXC-REC
           MOVE WS-X-CUST  TO EXC-CUST-ID
           MOVE WS-X-ACCT  TO EXC-ACCT-NO
           MOVE WS-X-TYPE  TO EXC-TYPE
           MOVE WS-X-FIELD TO EXC-FIELD
           MOVE WS-X-SRC   TO EXC-SRC-VAL
           MOVE WS-X-TGT   TO EXC-TGT-VAL
           WRITE EXC-REC
           IF WS-FS-EXC NOT = '00'
               MOVE 'EXCOUT WRITE ERROR' TO WS-NEW-REASON
               PERFORM 9900-ABORT
           ELSE
               ADD 1 TO WS-EXC-CNT
           END-IF.

       8000-WRITE-CONTROL.
           MOVE SPACES TO CTL-REC
           IF ABORTED
               MOVE 'MIGABORT' TO CTL-TAG
           ELSE
               MOVE 'MIGCTRL ' TO CTL-TAG
           END-IF
           MOVE WS-SRC-CNT      TO CTL-SRC-CNT
           MOVE WS-TGT-CNT      TO CTL-TGT-CNT
           MOVE WS-MATCHED-CNT  TO CTL-MATCHED
           MOVE WS-MISMATCH-CNT TO CTL-MISMATCH
           MOVE WS-MISSING-CNT  TO CTL-MISSING
           MOVE WS-EXTRA-CNT    TO CTL-EXTRA
           MOVE WS-SRC-TOT      TO CTL-SRC-TOT
           MOVE WS-TGT-TOT      TO CTL-TGT-TOT
           MOVE WS-REASON       TO CTL-REASON
           WRITE CTL-REC
           IF WS-FS-CTL NOT = '00'
               DISPLAY 'MIGMATCH: CTLOUT WRITE ERROR ' WS-FS-CTL
               MOVE 12 TO RETURN-CODE
           END-IF.

       8500-DISPLAY-SUMMARY.
           DISPLAY 'MIGMATCH SUMMARY'
           DISPLAY '  SOURCE RECORDS READ : ' WS-SRC-CNT
           DISPLAY '  TARGET RECORDS READ : ' WS-TGT-CNT
           DISPLAY '  MATCHED             : ' WS-MATCHED-CNT
           DISPLAY '  MISMATCHED RECORDS  : ' WS-MISMATCH-CNT
           DISPLAY '  MISSING IN TARGET   : ' WS-MISSING-CNT
           DISPLAY '  EXTRA IN TARGET     : ' WS-EXTRA-CNT
           DISPLAY '  EXCEPTION ROWS      : ' WS-EXC-CNT
           IF ABORTED
               DISPLAY '  *** ABORTED: ' WS-REASON
           END-IF.

       9000-CLOSE-FILES.
           CLOSE SRC-FILE
           CLOSE TGT-FILE
           CLOSE EXC-FILE
           CLOSE CTL-FILE.

      * Remember only the FIRST abort reason
       9900-ABORT.
           IF NOT ABORTED
               SET ABORTED TO TRUE
               MOVE WS-NEW-REASON TO WS-REASON
           END-IF.
