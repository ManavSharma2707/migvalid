//@HLQ@B JOB (@ACCT@),'MIG VSAM GDG',CLASS=@CLASS@,MSGCLASS=@MSGCLASS@,
//         NOTIFY=&SYSUID
//*-------------------------------------------------------------------
//* SETUP - run ONCE. Defines two GDG bases and the control-total KSDS.
//* (If DEFINE CLUSTER complains about a volume, ask your instructor
//*  which VOLUMES(xxxxxx) to add. Own HLQ only.)
//*-------------------------------------------------------------------
//SETUP    EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//SYSIN    DD *
  DEFINE GDG (NAME(@HLQ@.MIG.GATE.APPROVED) -
         LIMIT(10) SCRATCH NOEMPTY)
  DEFINE GDG (NAME(@HLQ@.MIG.GATE.REJECTED) -
         LIMIT(10) SCRATCH NOEMPTY)
  DEFINE CLUSTER (NAME(@HLQ@.MIG.CTRL.KSDS) -
         INDEXED KEYS(15 0) RECORDSIZE(120 120) -
         TRACKS(2 1) FREESPACE(10 10) SHAREOPTIONS(2 3))
/*
