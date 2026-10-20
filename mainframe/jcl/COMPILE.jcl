//@HLQ@C JOB (@ACCT@),'MIG COMPILE',CLASS=@CLASS@,MSGCLASS=@MSGCLASS@,
//         NOTIFY=&SYSUID
//*-------------------------------------------------------------------
//* COMPILE - compiles and link-edits MIGMATCH into @HLQ@.MIG.LOAD.
//* Uses the installation's COBOL procedure (read-only system libs).
//* Expected result: RC 0000 (RC 0004 = warnings only is fine).
//*-------------------------------------------------------------------
//COMPILE  EXEC @COBPROC@@LNGPRFX_PARM@
//COBOL.SYSIN  DD DSN=@HLQ@.MIG.COBOL(MIGMATCH),DISP=SHR
//LKED.SYSLMOD DD DSN=@HLQ@.MIG.LOAD(MIGMATCH),DISP=SHR
