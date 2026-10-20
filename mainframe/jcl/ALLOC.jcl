//@HLQ@A JOB (@ACCT@),'MIG ALLOC',CLASS=@CLASS@,MSGCLASS=@MSGCLASS@,
//         NOTIFY=&SYSUID
//*-------------------------------------------------------------------
//* ALLOC - run ONCE. Creates the libraries and the two input datasets.
//* Every dataset name starts with your own userid: @HLQ@.MIG.*
//*-------------------------------------------------------------------
//ALLOC    EXEC PGM=IEFBR14
//JCLLIB   DD DSN=@HLQ@.MIG.JCL,DISP=(NEW,CATLG,DELETE),
//            UNIT=@UNIT@,SPACE=(TRK,(15,15,20)),
//            DCB=(RECFM=FB,LRECL=80,BLKSIZE=27920)
//COBLIB   DD DSN=@HLQ@.MIG.COBOL,DISP=(NEW,CATLG,DELETE),
//            UNIT=@UNIT@,SPACE=(TRK,(15,15,20)),
//            DCB=(RECFM=FB,LRECL=80,BLKSIZE=27920)
//REXXLIB  DD DSN=@HLQ@.MIG.REXX,DISP=(NEW,CATLG,DELETE),
//            UNIT=@UNIT@,SPACE=(TRK,(15,15,20)),
//            DCB=(RECFM=FB,LRECL=80,BLKSIZE=27920)
//LOADLIB  DD DSN=@HLQ@.MIG.LOAD,DISP=(NEW,CATLG,DELETE),
//            UNIT=@UNIT@,SPACE=(TRK,(15,15,20)),
//            DCB=(RECFM=U,BLKSIZE=32760)
//SRCEXT   DD DSN=@HLQ@.MIG.SRC.EXTRACT,DISP=(NEW,CATLG,DELETE),
//            UNIT=@UNIT@,SPACE=(TRK,(15,15),RLSE),
//            DCB=(RECFM=FB,LRECL=80,BLKSIZE=27920)
//TGTEXT   DD DSN=@HLQ@.MIG.TGT.EXTRACT,DISP=(NEW,CATLG,DELETE),
//            UNIT=@UNIT@,SPACE=(TRK,(15,15),RLSE),
//            DCB=(RECFM=FB,LRECL=100,BLKSIZE=27900)
//SQLLOAD  DD DSN=@HLQ@.MIG.SQL.CUSTLOAD,DISP=(NEW,CATLG,DELETE),
//            UNIT=@UNIT@,SPACE=(TRK,(30,30),RLSE),
//            DCB=(RECFM=FB,LRECL=80,BLKSIZE=27920)
