"""Windows local setup: restricted init-dev or read-only prepare/owner approval."""
import argparse,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    from app.core.local_onboarding import prepare,approve,init_dev
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='action',required=True)
    check=commands.add_parser('prepare',help='SELECT-only; creates a pending private review, no approval')
    check.add_argument('--output',type=Path,required=True)
    owner=commands.add_parser('approve',help='Run only after explicit project-owner review of this exact request')
    owner.add_argument('--request',type=Path,required=True)
    owner.add_argument('--reviewed-sha256',required=True)
    owner.add_argument('--expected-system-identifier',required=True)
    owner.add_argument('--expected-data-directory',required=True)
    owner.add_argument('--owner',required=True)
    owner.add_argument('--approval-reference',required=True)
    owner.add_argument('--confirm-owner-approved-new-development',action='store_true')
    dev=commands.add_parser('init-dev',help='Automatic restricted local setup from the reviewed clean starter, never production')
    dev.add_argument('--confirm-local-development',action='store_true',help='Explicit noninteractive developer attestation, no owner consent implied')
    args=parser.parse_args();os.chdir(ROOT)
    if args.action=='init-dev':
        def confirm(observed):
            if args.confirm_local_development:return True
            if not sys.stdin.isatty():raise RuntimeError('PETRO configuration gate failed: interactive local-development confirmation required; use --confirm-local-development only for a verified private test environment')
            target=observed['identity']
            print('Verified local test target: '+target['database']+':'+str(target['port'])+'; system identifier '+target['system_identifier'])
            return input('Type LOCAL DEVELOPMENT to confirm this is your isolated test database, never production/shared staging: ').strip()=='LOCAL DEVELOPMENT'
        result=init_dev(confirm)
        if result['status']=='EXISTING_UNCHANGED':
            print('Existing local configuration is valid and unchanged ('+result['kind']+'); no conversion or overwrite performed.')
        else:print('Local development setup completed. You can now start Petro.')
        print('Next: python scripts/run_petro_dev.py')
        print('No migration, database write or worker startup was performed by setup.')
    elif args.action=='prepare':
        sha=prepare(args.output)
        print('AWAITING_OWNER_REVIEW; database read-only, no policy/approval/worker created.')
        print('Request SHA256: '+sha)
        print('Review the private request and catalog sidecar with the project owner. No secrets in shared reports.')
    else:
        approve(args.request,args.reviewed_sha256,args.expected_system_identifier,args.expected_data_directory,
                args.owner,args.approval_reference,args.confirm_owner_approved_new_development)
        print('Local configuration approved; existing PostgreSQL/UoW/schema guards PASS.')
        print('No migration, database write or worker startup performed. Runtime health NOT VERIFIED until Start All.')

if __name__=='__main__':
    try:main()
    except Exception as error:
        message=str(error) if isinstance(error,RuntimeError) and str(error).startswith('PETRO configuration gate failed:') else type(error).__name__
        from sqlalchemy.exc import DBAPIError
        if isinstance(error,DBAPIError):
            code=getattr(error.orig,'sqlstate',None) or 'unavailable'
            message='PostgreSQL read-only inspection failed (SQLSTATE '+code+'); check local connectivity/identity permissions/server logs; no approval installed'
        print('Onboarding STOP: '+message,file=sys.stderr)
        raise SystemExit(1) from None
