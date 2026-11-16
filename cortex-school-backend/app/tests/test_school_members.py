"""Invitation acceptance is authoritative in WorkOS; no local approval gate."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user
from core.config import settings
from modules.members.router import router
from modules.members.services import MemberLookupUnavailable, list_school_members
from modules.invitations.models import UserRoles
from modules.invitations.schemas import InvitationCreateRequest
from modules.invitations.services import parse_invitation_csv, _send_workos_invitation


def membership(user_id, *, organization_id='org_school', status='active', role='guardian'):
    return NS(id='membership_'+user_id, user_id=user_id,
              organization_id=organization_id, status=status, roles=[NS(slug=role)])


def page(members, after=None):
    return NS(data=members, list_metadata=NS(after=after))


class SchoolMemberTests(unittest.IsolatedAsyncioTestCase):
    async def test_invitation_always_sends_a_school_role(self):
        invitation=NS(email='parent@example.com',organization_id='org_school',role_slug=None,expires_in_days=7)
        client=AsyncMock()
        with patch.object(settings,'WORKOS_API_KEY','test-key'), \
             patch('modules.invitations.services.AsyncWorkOSClient') as factory:
            factory.return_value.__aenter__.return_value=client
            await _send_workos_invitation(invitation)
        args=client.user_management.send_invitation.call_args.kwargs
        self.assertEqual(args['role_slug'],'guardian')
        self.assertEqual(args['organization_id'],'org_school')

    async def test_accepted_member_is_listed_without_local_registration(self):
        client = AsyncMock()
        client.organization_membership.list_organization_memberships.return_value = page([
            membership('user_parent'), membership('user_teacher', role='teacher'),
            membership('user_suspended', status='inactive'),
            membership('user_foreign', organization_id='org_other'),
        ])
        async def get_user(user_id, **kwargs):
            return NS(id=user_id, first_name='New', last_name=user_id,
                      email=user_id+'@example.com')
        client.user_management.get_user.side_effect = get_user
        with patch.object(settings, 'WORKOS_API_KEY', 'test-key'), \
             patch('modules.members.services.AsyncWorkOSClient') as factory:
            factory.return_value.__aenter__.return_value = client
            result = await list_school_members('org_school')
        self.assertEqual({m['id'] for m in result}, {'user_parent', 'user_teacher'})
        self.assertTrue(all(m['status']=='active' for m in result))
        self.assertEqual(client.user_management.get_user.await_count, 2)
        args=client.organization_membership.list_organization_memberships.call_args.kwargs
        self.assertEqual(args['organization_id'],'org_school')
        self.assertEqual(args['statuses'],['active'])

    async def test_directory_fetches_following_pages(self):
        client=AsyncMock()
        client.organization_membership.list_organization_memberships.side_effect=[
            page([membership('user_one')], 'next'), page([membership('user_two')]),
        ]
        client.user_management.get_user.side_effect=lambda uid,**kw:NS(
            id=uid,first_name=None,last_name=None,email=uid+'@example.com')
        with patch.object(settings,'WORKOS_API_KEY','test-key'), \
             patch('modules.members.services.AsyncWorkOSClient') as factory:
            factory.return_value.__aenter__.return_value=client
            result=await list_school_members('org_school')
        self.assertEqual(len(result),2)
        self.assertEqual(client.organization_membership.list_organization_memberships.call_args.kwargs['after'],'next')

    async def test_no_organization_never_queries_provider(self):
        with patch('modules.members.services.AsyncWorkOSClient') as factory:
            with self.assertRaises(MemberLookupUnavailable):
                await list_school_members(None)
            factory.assert_not_called()


class SchoolMemberAuthorizationTests(unittest.TestCase):
    def test_single_and_csv_invitations_default_to_guardian(self):
        self.assertEqual(InvitationCreateRequest(email='parent@example.com').role_slug,UserRoles.GUARDIAN)
        self.assertEqual(parse_invitation_csv('email\nparent@example.com\n')[0].role_slug,UserRoles.GUARDIAN)
        self.assertEqual(parse_invitation_csv('email,role_slug\nteacher@example.com,teacher\n')[0].role_slug,UserRoles.TEACHER)

    def test_guardian_cannot_list_school_members(self):
        app=FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user]=lambda:{
            'user_id':'user_parent','organization_id':'org_school',
            'claims':{'roles':['guardian'],'permissions':[]},
        }
        with TestClient(app) as client:
            self.assertEqual(client.get('/members/').status_code,403)


if __name__=='__main__':
    unittest.main()
