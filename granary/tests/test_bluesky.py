"""Unit tests for bluesky.py.

Most tests are via files in testdata/.
"""
import copy
from io import BytesIO
from unittest import skip
from unittest.mock import ANY, patch

from oauth_dropins.webutil import testutil, util
from oauth_dropins.webutil.testutil import NOW, requests_response
from oauth_dropins.webutil.util import HTTP_TIMEOUT, trim_nulls
import requests

from ..bluesky import (
  AT_URI_PATTERN,
  at_uri_to_web_url,
  blob_to_url,
  Bluesky,
  did_web_to_url,
  from_as1,
  from_as1_to_strong_ref,
  LEXRPC_BASE,
  MAX_IMAGES,
  NO_AUTHENTICATED_LABEL,
  to_as1,
  url_to_did_web,
  web_url_to_at_uri,
)
from ..source import ALL, FRIENDS, INCLUDE_LINK, ME, SELF

ACTOR_AS = {
  'objectType': 'person',
  'id': 'did:web:alice.com',
  'displayName': 'Alice',
  'image': [{'url': 'https://alice.com/alice.jpg'}],
  'url': 'https://alice.com/',
  'summary': 'hi there',
}
ACTOR_PROFILE_VIEW_BSKY = {
  '$type': 'app.bsky.actor.defs#profileView',
  'did': 'did:web:alice.com',
  'handle': 'alice.com',
  'displayName': 'Alice',
  'avatar': 'https://alice.com/alice.jpg',
  'description': 'hi there',
  'fooOriginalDescription': 'hi there',
  'fooOriginalUrl': 'https://alice.com/',
}
NEW_BLOB = {  # new blob format: https://atproto.com/specs/data-model#blob-type
  '$type': 'blob',
  'ref': {'$link': 'bafkreim'},
  'mimeType': 'image/jpeg',
  'size': 154296,
}
NEW_BLOB_URL = 'https://bsky.social/xrpc/com.atproto.sync.getBlob?did=did:plc:foo&cid=bafkreim'
OLD_BLOB = {  # old blob format: https://atproto.com/specs/data-model#blob-type
  'cid': 'bafyjrot',
  'mimeType': 'image/jpeg',
}
OLD_BLOB_URL = 'https://bsky.social/xrpc/com.atproto.sync.getBlob?did=did:plc:foo&cid=bafyjrot'
ACTOR_PROFILE_BSKY = {
  '$type': 'app.bsky.actor.profile',
  'displayName': 'Alice',
  'avatar': NEW_BLOB,
  'banner': OLD_BLOB,
  'description': 'hi there',
  'fooOriginalDescription': 'hi there',
  'fooOriginalUrl': 'https://alice.com/',
}

POST_AS = {
  'objectType': 'activity',
  'id': 'at://did:alice/app.bsky.feed.post/tid',
  'verb': 'post',
  'actor': ACTOR_AS,
  'object': {
    'objectType': 'note',
    'id': 'at://did:alice/app.bsky.feed.post/tid',
    'url': 'https://bsky.app/profile/did:alice/post/tid',
    'published': '2007-07-07T03:04:05.000Z',
    'content': 'My original post',
  }
}
POST_BSKY = {
  '$type': 'app.bsky.feed.post',
  'text': 'My original post',
  'fooOriginalText': 'My original post',
  'fooOriginalUrl': 'https://bsky.app/profile/did:alice/post/tid',
  'createdAt': '2007-07-07T03:04:05.000Z',
}
POST_VIEW_BSKY = {
  '$type': 'app.bsky.feed.defs#postView',
  'uri': 'at://did:alice/app.bsky.feed.post/tid',
  'cid': '',
  'record': {
    '$type': 'app.bsky.feed.post',
    'text': 'My original post',
    'fooOriginalText': 'My original post',
    'fooOriginalUrl': 'https://bsky.app/profile/alice.com/post/tid',
    'createdAt': '2007-07-07T03:04:05.000Z',
  },
  'author': {
    '$type': 'app.bsky.actor.defs#profileViewBasic',
    'did': '',
    'handle': '',
  },
  'replyCount': 0,
  'repostCount': 0,
  'likeCount': 0,
  'indexedAt': '2022-01-02T03:04:05.000Z',
}

POST_AUTHOR_AS = copy.deepcopy(POST_AS)
POST_AUTHOR_AS['object'].update({
  'author': ACTOR_AS,
  'url': 'https://bsky.app/profile/alice.com/post/tid',
})
POST_AUTHOR_PROFILE_AS = copy.deepcopy(POST_AUTHOR_AS)
POST_AUTHOR_PROFILE_AS['object']['author'].update({
  'username': 'alice.com',
  'url': 'https://bsky.app/profile/alice.com',
  'urls': ['https://bsky.app/profile/alice.com', 'https://alice.com/'],
})
POST_AUTHOR_PROFILE_AS['actor'].update({
  'username': 'alice.com',
  'url': 'https://bsky.app/profile/alice.com',
  'urls': ['https://bsky.app/profile/alice.com', 'https://alice.com/'],
})
POST_AUTHOR_BSKY = copy.deepcopy(POST_VIEW_BSKY)
POST_AUTHOR_BSKY['author'] = {
  **ACTOR_PROFILE_VIEW_BSKY,
  '$type': 'app.bsky.actor.defs#profileViewBasic',
}
POST_FEED_VIEW_BSKY = {
  '$type': 'app.bsky.feed.defs#feedViewPost',
  'post': POST_AUTHOR_BSKY,
}

FACET_LINK = {
  '$type': 'app.bsky.richtext.facet',
  'features': [{
    '$type': 'app.bsky.richtext.facet#link',
    'uri': 'http://my/link',
  }],
  'index': {
    'byteStart': 3,
    'byteEnd': 11,
  },
}
TAG_LINK = {
  'objectType': 'article',
  'url': 'http://my/link',
  'displayName': 'original',
  'startIndex': 3,
  'length': 8,
}
POST_BSKY_FACET_HASHTAG = {
  '$type': 'app.bsky.feed.post',
  'text': 'foo #hache-☕ bar',
  'fooOriginalText': 'foo #hache-☕ bar',
  'createdAt': '2007-07-07T03:04:05.000Z',
  'facets': [{
    '$type': 'app.bsky.richtext.facet',
    'features': [{
      '$type': 'app.bsky.richtext.facet#tag',
      'tag': 'hache-☕',
    }],
    'index': {
      'byteStart': 4,
      'byteEnd': 14,
    },
  }],
}
NOTE_AS_TAG_HASHTAG = {
  'objectType': 'note',
  'published': '2007-07-07T03:04:05.000Z',
  'content': 'foo #hache-☕ bar',
  'tags': [{
    'objectType': 'hashtag',
    'displayName': 'hache-☕',
    'startIndex': 4,
    'length': 8,
  }],
}
FACET_MENTION = {
  '$type': 'app.bsky.richtext.facet',
  'features': [{
    '$type': 'app.bsky.richtext.facet#mention',
    'did': 'did:plc:foo',
  }],
  'index': {
    'byteStart': 5,
    'byteEnd': 12,
  },
}
TAG_MENTION_DID = {
  'objectType': 'mention',
  'url': 'did:plc:foo',
  'displayName': 'you.com',
}
TAG_MENTION_URL = {
  'objectType': 'mention',
  'url': 'https://bsky.app/profile/did:plc:foo',
  'displayName': 'you.com',
}
NOTE_AS_TAG_MENTION_URL = {
  'objectType': 'note',
  'content': 'foo @you.com bar',
  'tags': [{
    **TAG_MENTION_URL,
    'startIndex': 4,
    'length': 8,
  }]
}
NOTE_AS_TAG_MENTION_DID = copy.deepcopy(NOTE_AS_TAG_MENTION_URL)
NOTE_AS_TAG_MENTION_DID['tags'][0].update(TAG_MENTION_DID)
POST_BSKY_FACET_MENTION = {
  '$type': 'app.bsky.feed.post',
  'text': 'foo @you.com bar',
  'fooOriginalText': 'foo @you.com bar',
  'createdAt': '2022-01-02T03:04:05.000Z',
  'facets': [{
    '$type': 'app.bsky.richtext.facet',
    'features': [{
      '$type': 'app.bsky.richtext.facet#mention',
      'did': 'did:plc:foo',
    }],
    'index': {
      'byteStart': 4,
      'byteEnd': 12,
    },
  }],
}
EMBED_EXTERNAL = {
  'description': '',
  'title': 'a link',
  'uri': 'http://my/link',
}
EMBED_EXTERNAL_ATTACHMENT = {
  'objectType': 'link',
  'url': 'http://my/link',
  'displayName': 'a link',
}
POST_AS_EMBED = {
  **POST_AS['object'],
  'attachments': [EMBED_EXTERNAL_ATTACHMENT],
}
POST_BSKY_EMBED = {
  **POST_BSKY,
  'embed': {
    '$type': 'app.bsky.embed.external',
    'external': {
      '$type': 'app.bsky.embed.external#external',
      **EMBED_EXTERNAL,
    },
  },
}

POST_VIEW_BSKY_EMBED = copy.deepcopy(POST_VIEW_BSKY)
POST_VIEW_BSKY_EMBED['record'].update({
  'embed': POST_BSKY_EMBED['embed'],
  'fooOriginalUrl': 'https://bsky.app/profile/did:alice/post/tid',
})
POST_VIEW_BSKY_EMBED['embed'] = {
  '$type': 'app.bsky.embed.external#view',
  'external': {
    '$type': 'app.bsky.embed.external#viewExternal',
    **EMBED_EXTERNAL,
  },
}
POST_AS_IMAGES = copy.deepcopy(POST_AS)
POST_AS_IMAGES['object']['image'] = [{
  'url': NEW_BLOB_URL,
  'displayName': 'my alt text',
}]

EMBED_IMAGES = {
  '$type': 'app.bsky.embed.images',
  'images': [{
    '$type': 'app.bsky.embed.images#image',
    'alt': 'my alt text',
    'image': NEW_BLOB,
  }],
}
POST_BSKY_IMAGES = copy.deepcopy(POST_BSKY)
POST_BSKY_IMAGES['embed'] = EMBED_IMAGES

POST_VIEW_BSKY_IMAGES = copy.deepcopy(POST_VIEW_BSKY)
POST_VIEW_BSKY_IMAGES['record']['embed'] = EMBED_IMAGES
POST_VIEW_BSKY_IMAGES['embed'] = {
  '$type': 'app.bsky.embed.images#view',
  'images': [{
    '$type': 'app.bsky.embed.images#viewImage',
    'alt': 'my alt text',
    'fullsize': NEW_BLOB_URL,
    'thumb': NEW_BLOB_URL,
  }],
}

REPLY_AS = {
  'objectType': 'activity',
  'verb': 'post',
  'object': {
    'objectType': 'comment',
    'published': '2008-08-08T03:04:05.000Z',
    'content': 'I hereby reply to this',
    'id': 'at://did/app.bsky.feed.post/tid',
    'url': 'https://bsky.app/profile/did/post/tid',
    'inReplyTo': [{
      'id': 'at://did:alice/app.bsky.feed.post/parent-tid',
      'url': 'https://bsky.app/profile/did:alice/post/parent-tid',
    }],
  },
}
REPLY_BSKY = {
  '$type': 'app.bsky.feed.post',
  'text': 'I hereby reply to this',
  'fooOriginalText': 'I hereby reply to this',
  'fooOriginalUrl': 'https://bsky.app/profile/did/post/tid',
  'createdAt': '2008-08-08T03:04:05.000Z',
  'reply': {
    '$type': 'app.bsky.feed.post#replyRef',
    'root': {
      'uri': 'at://did:alice/app.bsky.feed.post/parent-tid',
      'cid': '',
    },
    'parent': {
      'uri': 'at://did:alice/app.bsky.feed.post/parent-tid',
      'cid': '',
    },
  },
}
REPLY_POST_VIEW_BSKY = copy.deepcopy(POST_VIEW_BSKY)
REPLY_POST_VIEW_BSKY.update({
  'uri': 'at://did/app.bsky.feed.post/tid',
  'record': REPLY_BSKY,
})

# Replies to non-Bluesky posts, but which are syndicated to Bluesky.
# The object will have several inReplyTo URLs - Granary should pick the
# correct one.
REPLY_TO_WEBSITE_AS = copy.deepcopy(REPLY_AS)
REPLY_TO_WEBSITE_AS['object']['inReplyTo'] = [
  {'url': 'http://example.com/post'},
  {'url': 'https://mastodon.social/@alice/post'},
  {'url': 'https://bsky.app/profile/did:alice/post/parent-tid'},
]

REPOST_AS = {
  'objectType': 'activity',
  'verb': 'share',
  'actor': {
    'objectType': 'person',
    'id': 'did:web:bob.com',
    'displayName': 'Bob',
    'url': 'https://bsky.app/profile/bob.com',
    'urls': ['https://bsky.app/profile/bob.com', 'https://bob.com/'],
  },
  'object': POST_AUTHOR_PROFILE_AS['object'],
}
REPOST_PROFILE_AS = copy.deepcopy(REPOST_AS)
REPOST_PROFILE_AS['actor'].update({
  'username': 'bob.com',
    'url': 'https://bsky.app/profile/bob.com',
    'urls': ['https://bsky.app/profile/bob.com', 'https://bob.com/'],
})

REPOST_BSKY = {
  '$type': 'app.bsky.feed.repost',
  'subject': {
    'uri': 'at://did:alice/app.bsky.feed.post/tid',
    'cid': '',
  },
  'createdAt': '2022-01-02T03:04:05.000Z',
}
REPOST_BSKY_REASON = {
  '$type': 'app.bsky.feed.defs#reasonRepost',
  'by': {
    '$type': 'app.bsky.actor.defs#profileViewBasic',
    'did': 'did:web:bob.com',
    'handle': 'bob.com',
    'displayName': 'Bob',
    'fooOriginalUrl': 'https://bsky.app/profile/bob.com',
  },
  'indexedAt': '2022-01-02T03:04:05.000Z',
}
REPOST_BSKY_FEED_VIEW_POST = {
  '$type': 'app.bsky.feed.defs#feedViewPost',
  'post': copy.deepcopy(POST_AUTHOR_BSKY),
  'reason': REPOST_BSKY_REASON,
}
REPOST_BSKY_FEED_VIEW_POST['post']['author']['fooOriginalUrl'] = \
  'https://bsky.app/profile/alice.com'

THREAD_REPLY_AS = copy.deepcopy(REPLY_AS['object'])
THREAD_REPLY_AS['id'] = 'tag:bsky.app:at://did/app.bsky.feed.post/tid'
THREAD_REPLY2_AS = copy.deepcopy(REPLY_AS['object'])
THREAD_REPLY2_AS['id'] = 'tag:bsky.app:at://did:alice/app.bsky.feed.post/tid2'
THREAD_REPLY2_AS['url'] = 'https://bsky.app/profile/did:alice/post/tid2'
THREAD_REPLY2_AS['inReplyTo'] = [{
  'id': 'at://did:alice/app.bsky.feed.post/tid',
  'url': 'https://bsky.app/profile/did:alice/post/tid'
}]
THREAD_AS = copy.deepcopy(POST_AS)
THREAD_AS['object']['replies'] = {'items': [THREAD_REPLY_AS, THREAD_REPLY2_AS]}
THREAD_AS['object']['author'] = {
  **ACTOR_AS,
  'username': 'alice.com',
  'url': 'https://bsky.app/profile/alice.com',
  'urls': ['https://bsky.app/profile/alice.com', 'https://alice.com/'],
}
THREAD_AS['object']['url'] = 'https://bsky.app/profile/alice.com/post/tid'
THREAD_AS['actor'].update({
  'username': 'alice.com',
  'url': 'https://bsky.app/profile/alice.com',
  'urls': ['https://bsky.app/profile/alice.com', 'https://alice.com/'],
})

THREAD_BSKY = {
  '$type': 'app.bsky.feed.defs#threadViewPost',
  'post': POST_AUTHOR_BSKY,
  'replies': [{
    '$type': 'app.bsky.feed.defs#threadViewPost',
    'post': copy.deepcopy(REPLY_POST_VIEW_BSKY),
    'replies': [{
      '$type': 'app.bsky.feed.defs#threadViewPost',
      'post': copy.deepcopy(REPLY_POST_VIEW_BSKY),
      'replies': [],
    }],
  }],
}
THREAD_BSKY['replies'][0]['replies'][0]['post'].update({
  'uri': 'at://did:alice/app.bsky.feed.post/tid2'
})
THREAD_BSKY['replies'][0]['replies'][0]['post']['record']['reply'].update({
  'parent': {
    '$type': 'com.atproto.repo.strongRef',
    'uri': 'at://did:alice/app.bsky.feed.post/tid',
    'cid': ''
  }
})

BLOB = {
  '$type': 'blob',
  'ref': 'a CID',
  'mimeType': 'foo/bar',
  'size': 13,
}

POST_FEED_VIEW_WITH_LIKES_BSKY = copy.deepcopy(POST_FEED_VIEW_BSKY)
POST_FEED_VIEW_WITH_LIKES_BSKY['post']['likeCount'] = 1
POST_FEED_VIEW_WITH_REPOSTS_BSKY = copy.deepcopy(POST_FEED_VIEW_BSKY)
POST_FEED_VIEW_WITH_REPOSTS_BSKY['post']['repostCount'] = 1
POST_FEED_VIEW_WITH_REPLIES_BSKY = copy.deepcopy(POST_FEED_VIEW_BSKY)
POST_FEED_VIEW_WITH_REPLIES_BSKY['post']['replyCount'] = 1

LIKE_AS = {
  'objectType': 'activity',
  'verb': 'like',
  'id': 'at://alice.com/app.bsky.feed.like/123',
  'url': 'https://bsky.app/profile/did:alice/post/tid#liked_by_alice.com',
  'object': 'at://did:alice/app.bsky.feed.post/tid',
}
LIKE_BSKY = {
  '$type': 'app.bsky.feed.like',
  'subject': {
    'uri': 'at://did:alice/app.bsky.feed.post/tid',
    'cid': '',
  },
  'createdAt': '2022-01-02T03:04:05.000Z',
}
GET_LIKES_LIKE_BSKY = {
  '$type': 'app.bsky.feed.getLikes#like',
  'indexedAt': '2022-01-02T03:04:05.000Z',
  'createdAt': '2008-08-08T03:04:05.000Z',
  'actor': ACTOR_PROFILE_VIEW_BSKY,
}

POST_AUTHOR_PROFILE_WITH_LIKES_AS = copy.deepcopy(POST_AUTHOR_PROFILE_AS)
POST_AUTHOR_PROFILE_WITH_LIKES_AS['object']['tags'] = [{
  'author': copy.deepcopy(ACTOR_AS),
  'id': 'tag:bsky.app:at://did:alice/app.bsky.feed.post/tid_liked_by_did:web:alice.com',
  'objectType': 'activity',
  'verb': 'like',
  'url': 'https://bsky.app/profile/alice.com/post/tid#liked_by_did:web:alice.com',
  'object': {'url': 'https://bsky.app/profile/alice.com/post/tid'}
}]
POST_AUTHOR_PROFILE_WITH_LIKES_AS['object']['tags'][0]['author'].update({
  'id': 'tag:bsky.app:did:web:alice.com',
  'username': 'alice.com',
  'url': 'https://bsky.app/profile/alice.com',
  'urls': ['https://bsky.app/profile/alice.com', 'https://alice.com/'],
})

POST_AUTHOR_PROFILE_WITH_REPOSTS_AS = copy.deepcopy(POST_AUTHOR_PROFILE_AS)
POST_AUTHOR_PROFILE_WITH_REPOSTS_AS['object']['tags'] = [{
  'author': copy.deepcopy(ACTOR_AS),
  'id': 'tag:bsky.app:at://did:alice/app.bsky.feed.post/tid_reposted_by_did:web:alice.com',
  'objectType': 'activity',
  'verb': 'share',
  'url': 'https://bsky.app/profile/alice.com/post/tid#reposted_by_did:web:alice.com',
  'object': {'url': 'https://bsky.app/profile/alice.com/post/tid'}
}]
POST_AUTHOR_PROFILE_WITH_REPOSTS_AS['object']['tags'][0]['author'].update({
  'id': 'tag:bsky.app:did:web:alice.com',
  'username': 'alice.com',
  'url': 'https://bsky.app/profile/alice.com',
  'urls': ['https://bsky.app/profile/alice.com', 'https://alice.com/'],
})

FOLLOW_AS = {
  'objectType': 'activity',
  'verb': 'follow',
  'actor': 'did:alice',
  'object': 'did:bob',
}
FOLLOW_BSKY = {
  '$type': 'app.bsky.graph.follow',
  'subject': 'did:bob',
  'createdAt': '2022-01-02T03:04:05.000Z'
}


class BlueskyTest(testutil.TestCase):

  def setUp(self):
    super().setUp()
    self.bs = Bluesky(handle='handull', did='did:dyd', access_token='towkin')
    util.now = lambda **kwargs: testutil.NOW

  def assert_equals(self, expected, actual, **kwargs):
    return super().assert_equals(expected, actual, in_order=True, **kwargs)

  def assert_call(self, mock, method, json=None):
    mock.assert_any_call(f'https://bsky.social/xrpc/{method}', data=None,
                         json=json, headers={
                           'Authorization': 'Bearer towkin',
                           'Content-Type': 'application/json',
                           'User-Agent': util.user_agent,
                         })

  @staticmethod
  def from_as1(obj, **kwargs):
    return from_as1(obj, original_fields_prefix='foo', **kwargs)

  def test_at_uri_pattern(self):
    for input, expected in [
        ('', False),
        ('foo', False),
        ('http://bar', False),
        ('at://', False),
        ('at:////', False),
        ('at://x/y/z', True),
        ('at://x / y/z', False),
        (' at://x/y/z ', False),
        ('at://did:plc:foo/a.b/123', True),
    ]:
      with self.subTest(input=input):
        self.assertEqual(expected, AT_URI_PATTERN.match(input) is not None)

  def test_url_to_did_web(self):
    for bad in None, '', 'foo', 'did:web:bar.com':
      with self.assertRaises(ValueError):
        url_to_did_web(bad)

    self.assertEqual('did:web:foo.com', url_to_did_web('https://foo.com'))
    self.assertEqual('did:web:foo.com', url_to_did_web('https://foo.com/'))
    self.assertEqual('did:web:foo.com', url_to_did_web('https://foo.com:3000'))
    self.assertEqual('did:web:foo.bar.com', url_to_did_web('https://foo.bar.com/baz/baj'))

  def test_did_web_to_url(self):
    for bad in None, '', 'foo' 'https://bar.com', 'did:web:foo.com:path':
      with self.assertRaises(ValueError):
        did_web_to_url(bad)

    self.assertEqual('https://foo.com/', did_web_to_url('did:web:foo.com'))
    self.assertEqual('https://foo.bar.com/', did_web_to_url('did:web:foo.bar.com'))

  def test_user_url(self):
    self.assertEqual('https://bsky.app/profile/snarfed.org',
                     Bluesky.user_url('snarfed.org'))

    self.assertEqual('https://bsky.app/profile/snarfed.org',
                     Bluesky.user_url('@snarfed.org'))

  def test_user_to_actor(self):
    self.assert_equals({
      'objectType': 'person',
      'displayName': 'Alice',
      'summary': 'hi there',
    }, Bluesky.user_to_actor(ACTOR_PROFILE_BSKY))

  def test_post_url(self):
    self.assertEqual('https://bsky.app/profile/snarfed.org/post/3jv3wdw2hkt25',
                     Bluesky.post_url('snarfed.org', '3jv3wdw2hkt25'))

  def test_at_uri_to_web_url(self):
    self.assertEqual(None, at_uri_to_web_url(''))

    at_uri = 'at://did:plc:asdf/app.bsky.feed.post/3jv3wdw2hkt25'
    self.assertEqual(
      'https://bsky.app/profile/did:plc:asdf/post/3jv3wdw2hkt25',
      at_uri_to_web_url(at_uri))
    self.assertEqual(
      'https://bsky.app/profile/snarfed.org/post/3jv3wdw2hkt25',
      at_uri_to_web_url(at_uri, handle='snarfed.org'))

    at_uri_profile = 'at://did:plc:asdf'
    self.assertEqual(
      'https://bsky.app/profile/did:plc:asdf',
      at_uri_to_web_url(at_uri_profile))
    self.assertEqual(
      'https://bsky.app/profile/snarfed.org',
      at_uri_to_web_url(at_uri_profile, handle='snarfed.org'))

    self.assertEqual(
      'https://bsky.app/profile/did:plc:asdf/lists/123',
      at_uri_to_web_url('at://did:plc:asdf/app.bsky.graph.list/123'))

    with self.assertRaises(ValueError):
      at_uri_to_web_url('http://not/at/uri')

  def test_web_url_to_at_uri(self):
    for url, expected in (
        ('', None),
        ('https://bsky.app/profile/foo.com',
         'at://foo.com/app.bsky.actor.profile/self'),
        ('https://bsky.app/profile/did:plc:foo',
         'at://did:plc:foo/app.bsky.actor.profile/self'),
        ('https://bsky.app/profile/did:plc:foo/post/3jv3wdw2hkt25',
         'at://did:plc:foo/app.bsky.feed.post/3jv3wdw2hkt25'),
        ('https://bsky.app/profile/bsky.app/feed/mutuals',
         'at://bsky.app/app.bsky.feed.generator/mutuals'),
    ):
      self.assertEqual(expected, web_url_to_at_uri(url))

      self.assertEqual(
        'at://did:plc:foo/app.bsky.actor.profile/self',
        web_url_to_at_uri('https://bsky.app/profile/foo.com', handle='foo.com',
                          did='did:plc:foo'))

      self.assertEqual(
        'at://foo.com/app.bsky.actor.profile/self',
        web_url_to_at_uri('https://bsky.app/profile/foo.com', did='did:plc:foo')
      )

      self.assertEqual(
        'at://foo.com/app.bsky.actor.profile/self',
        web_url_to_at_uri('https://bsky.app/profile/foo.com', handle='foo.com')
      )

      self.assertEqual(
        'at://foo.com/app.bsky.actor.profile/self',
        web_url_to_at_uri('https://bsky.app/profile/foo.com',
                          handle='alice.com', did='did:plc:foo'))

    for url in ('at://foo', 'http://not/bsky.app', 'https://bsky.app/x'):
      with self.assertRaises(ValueError):
        web_url_to_at_uri(url)

  def test_from_as1_to_strong_ref(self):
    for obj, at_uri in (
        ('', ''),
        ('at://foo/bar/baz', 'at://foo/bar/baz'),
        ('https://bsky.app/profile/foo/post/bar', 'at://foo/app.bsky.feed.post/bar'),
        ('baz biff', ''),
        ({}, ''),
        ({'id': 'foo'}, ''),
        ({'id': 'at://foo/bar/baz'}, 'at://foo/bar/baz'),
        ({'url': 'https://bsky.app/profile/foo/post/bar'},
         'at://foo/app.bsky.feed.post/bar'),
        ({'url': ['at://foo/bar/baz', 'xyz']}, 'at://foo/bar/baz'),
    ):
      with self.subTest(obj=obj):
        self.assertEqual({'uri': at_uri, 'cid': ''}, from_as1_to_strong_ref(obj))

  @patch('requests.get')
  def test_from_as1_to_strong_ref_client_value_false(self, mock_get):
    ref = {
      'uri': 'at://did:foo/app.bsky.feed.post/bar',
      'cid': 'my-syd',
    }
    mock_get.return_value = requests_response({**ref, 'value': {'x': 'y'}})

    self.assertEqual(ref, from_as1_to_strong_ref({
      'url': 'https://bsky.app/profile/did:foo/post/bar',
    }, client=self.bs._client, value=False))

    self.assert_call(mock_get,
                     'com.atproto.repo.getRecord'
                     '?repo=did%3Afoo&collection=app.bsky.feed.post&rkey=bar')

  @patch('requests.get')
  def test_from_as1_to_strong_ref_client_value_true(self, mock_get):
    record = {
      'uri': 'at://did:foo/app.bsky.feed.post/bar',
      'cid': 'my-syd',
      'value': {'x': 'y'},
    }
    mock_get.return_value = requests_response(record)

    self.assertEqual(record, from_as1_to_strong_ref({
      'url': 'https://bsky.app/profile/did:foo/post/bar',
    }, client=self.bs._client, value=True))

    self.assert_call(mock_get,
                     'com.atproto.repo.getRecord'
                     '?repo=did%3Afoo&collection=app.bsky.feed.post&rkey=bar')

  @patch('requests.get')
  def test_from_as1_to_strong_ref_client_resolve_handle_to_did(self, mock_get):
    mock_get.side_effect = [
      requests_response({'did': 'did:alice'}),  # resolveHandle
      requests_response({'cid': 'my-syd'}),     # getRecord
    ]

    self.assertEqual({'cid': 'my-syd'},
                     from_as1_to_strong_ref(
                       {'url': 'https://bsky.app/profile/foo/post/bar'},
                       client=self.bs._client))

    self.assert_call(mock_get, 'com.atproto.identity.resolveHandle?handle=foo')
    self.assert_call(mock_get,
                     'com.atproto.repo.getRecord'
                     '?repo=did%3Aalice&collection=app.bsky.feed.post&rkey=bar')

  def test_from_as1_missing_objectType_or_verb(self):
    for obj in [
        {'content': 'foo'},
        {'objectType': 'activity', 'content': 'foo'},
    ]:
      with self.subTest(obj=obj):
        with self.assertRaises(ValueError):
          self.from_as1(obj)

  def test_from_as1_unsupported_out_type(self):
    with self.assertRaises(ValueError):
      self.from_as1({'objectType': 'image'}, out_type='foo')  # no matching objectType

    with self.assertRaises(ValueError):
      self.from_as1({'objectType': 'person'}, out_type='foo')  # mismatched out_type

  def test_from_as1_post(self):
    self.assert_equals(POST_BSKY, self.from_as1(POST_AS))

  def test_from_as1_post_out_type_postView(self):
    expected = copy.deepcopy(POST_VIEW_BSKY)
    got = self.from_as1(POST_AS, out_type='app.bsky.feed.defs#postView')
    expected['record']['fooOriginalUrl'] = 'https://bsky.app/profile/did:alice/post/tid'
    self.assert_equals(expected, got)

  def test_from_as1_post_feed_view(self):
    self.assert_equals(POST_AUTHOR_PROFILE_AS['object'], to_as1(POST_FEED_VIEW_BSKY))

  def test_from_as1_post_out_type_feedViewPost(self):
    got = self.from_as1(POST_AUTHOR_AS, out_type='app.bsky.feed.defs#feedViewPost')
    self.assert_equals(POST_FEED_VIEW_BSKY, got)

  def test_from_as1_post_with_author(self):
    expected = copy.deepcopy(POST_AUTHOR_BSKY)
    got = self.from_as1(POST_AUTHOR_AS, out_type='app.bsky.feed.defs#postView')
    self.assert_equals(expected, got)

  def test_from_as1_post_html_skips_tag_indices(self):
    post_as = copy.deepcopy(POST_AS)
    post_as['object'].update({
      'content': '<em>some html</em>',
      'content_is_html': True,
      # not set because content is HTML
      # 'tags': [TAG_LINK],
    })

    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'text': '_some html_',
      'fooOriginalText': '<em>some html</em>',
      'fooOriginalUrl': 'https://bsky.app/profile/did:alice/post/tid',
      'createdAt': '2007-07-07T03:04:05.000Z',
    }, self.from_as1(post_as))

  def test_from_as1_post_without_tag_indices(self):
    post_as = copy.deepcopy(POST_AS)
    post_as['object']['tags'] = [{
      'url': 'http://my/link',
    }]

    # no facet
    self.assert_equals(POST_BSKY, self.from_as1(post_as))

  @patch.dict(LEXRPC_BASE.defs['app.bsky.feed.post']['record']['properties']['text'],
              maxGraphemes=15)
  def test_from_as1_post_truncate_adds_link_embed(self):
    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'text': 'more than […]',
      'fooOriginalText': 'more than ten chars long',
      'fooOriginalUrl': 'http://my.inst/post',
      'createdAt': '2022-01-02T03:04:05.000Z',
      'embed': {
        '$type': 'app.bsky.embed.external',
        'external': {
          '$type': 'app.bsky.embed.external#external',
          'description': '',
          'title': 'Original post on my.inst',
          'uri': 'http://my.inst/post',
        },
      },
    }, self.from_as1({
      'objectType': 'note',
      'url': 'http://my.inst/post',
      'content': 'more than ten chars long',
    }))

  def test_from_as1_post_truncate_full_length(self):
    # check that we use the app.bsky.feed.post limit, not app.bsky.actor.profile's
    # https://github.com/snarfed/bridgy-fed/issues/1128
    content = 'Das #BSW spricht den ganzen Tag von Frieden und Diplomatie. Beide Seiten anhören angeblich. Aber wenn das Opfer des illegalen Angriffskriegs was zu sagen hat, dann verlasssen sie aus Protest den Saal? Deutlicher kann man nicht machen, dass man möchte, dass der Angreifer gewinnt.'
    self.assert_equals(content, self.from_as1({
      'objectType': 'note',
      'url': 'http://my.inst/post',
      'content': content,
    })['text'])

  @patch.dict(LEXRPC_BASE.defs['app.bsky.feed.post']['record']['properties']['text'],
              maxGraphemes=45)
  def test_from_as1_post_with_images_truncated_puts_original_post_link_in_text(self):
    content = 'hello hello hello hello hello hello hello hello hello'
    self.assert_equals({
      **POST_BSKY_IMAGES,
      'text': 'hello hello […] \n\n[Original post on my.inst]',
      'fooOriginalText': content,
      'fooOriginalUrl': 'http://my.inst/post',
      'facets': [{
        '$type': 'app.bsky.richtext.facet',
        'features': [{
          '$type': 'app.bsky.richtext.facet#link',
          'uri': 'http://my.inst/post',
        }],
        'index': {
          'byteStart': 18,
          'byteEnd': 46,
        },
      }],
    }, self.from_as1({
      **POST_AS_IMAGES['object'],
      'content': content,
      'url': 'http://my.inst/post',
    }, blobs={NEW_BLOB_URL: NEW_BLOB}))

  @patch.dict(LEXRPC_BASE.defs['app.bsky.feed.post']['record']['properties']['text'],
              maxGraphemes=51)
  def test_from_as1_post_with_images_video_truncated_original_post_link_in_text(self):
    self.assert_equals({
      **POST_BSKY_IMAGES,
      'text': 'My […] \n\n[Video] [Original post on my.inst]',
      'fooOriginalUrl': 'http://my.inst/post',
      'facets': [{
        '$type': 'app.bsky.richtext.facet',
        'features': [{
          '$type': 'app.bsky.richtext.facet#link',
          'uri': 'http://my.inst/post',
        }],
        'index': {
          'byteStart': 9,
          'byteEnd': 45,
        },
      }],
    }, self.from_as1({
      **POST_AS_IMAGES['object'],
      'url': 'http://my.inst/post',
      'attachments': [{
        'objectType': 'video',
        'stream': {'url': 'https://a/cool/vid'},
      }],
    }, blobs={NEW_BLOB_URL: NEW_BLOB}))

  @patch.dict(LEXRPC_BASE.defs['app.bsky.feed.post']['record']['properties']['text'],
              maxGraphemes=40)
  def test_from_as1_post_with_images_removes_facets_beyond_truncation(self):
    content = 'hello <a href="http://foo">link</a> goodbye goodbye goodbye goodbye'
    self.assert_equals({
      **POST_BSKY_IMAGES,
      'text': 'hello […] \n\n[Original post on my.inst]',
      'fooOriginalText': content,
      'fooOriginalUrl': 'http://my.inst/post',
      'facets': [{
        '$type': 'app.bsky.richtext.facet',
        'features': [{
          '$type': 'app.bsky.richtext.facet#link',
          'uri': 'http://my.inst/post',
        }],
        'index': {
          'byteStart': 12,
          'byteEnd': 40,
        },
      }],
    }, self.from_as1({
      **POST_AS_IMAGES['object'],
      'content': content,
      'url': 'http://my.inst/post',
    }, blobs={NEW_BLOB_URL: NEW_BLOB}))

  @patch.dict(LEXRPC_BASE.defs['app.bsky.feed.post']['record']['properties']['text'],
              maxGraphemes=40)
  def test_from_as1_post_with_images_truncates_facet_that_overlaps_truncation(self):
    content = '<a href="http://foo">hello link text</a> goodbye goodbye goodbye goodbye'
    self.assert_equals({
      **POST_BSKY_IMAGES,
      'text': 'hello […] \n\n[Original post on my.inst]',
      'fooOriginalText': content,
      'fooOriginalUrl': 'http://my.inst/post',
      'facets': [{
        '$type': 'app.bsky.richtext.facet',
        'features': [{
          '$type': 'app.bsky.richtext.facet#link',
          'uri': 'http://my.inst/post',
        }],
        'index': {
          'byteStart': 12,
          'byteEnd': 40,
        },
      }, {
        '$type': 'app.bsky.richtext.facet',
        'features': [{
          '$type': 'app.bsky.richtext.facet#link',
          'uri': 'http://foo',
        }],
        'index': {
          'byteStart': 0,
          'byteEnd': 5,
        },
      }],
    }, self.from_as1({
      **POST_AS_IMAGES['object'],
      'content': content,
      'url': 'http://my.inst/post',
    }, blobs={NEW_BLOB_URL: NEW_BLOB}))

  @patch.dict(LEXRPC_BASE.defs['app.bsky.feed.post']['record']['properties']['text'],
              maxGraphemes=15)
  def test_from_as1_post_truncate_fallback_to_id_if_no_url(self):
    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'text': 'more than […]',
      'fooOriginalText': 'more than ten chars long',
      'fooOriginalUrl': 'http://my.inst/post',
      'createdAt': '2022-01-02T03:04:05.000Z',
      'embed': {
        '$type': 'app.bsky.embed.external',
        'external': {
          '$type': 'app.bsky.embed.external#external',
          'description': '',
          'title': 'Original post on my.inst',
          'uri': 'http://my.inst/post',
        },
      },
    }, self.from_as1({
      'objectType': 'note',
      'id': 'http://my.inst/post',
      'content': 'more than ten chars long',
    }))

  def test_from_as1_post_preserve_whitespace_plain_text(self):
    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'text': 'hello\n  there\n\nok',
      'fooOriginalText': 'hello\n  there\n\nok',
      'createdAt': '2022-01-02T03:04:05.000Z',
    }, self.from_as1({
      'objectType': 'note',
      'content': 'hello\n  there\n\nok',
    }))

  def test_from_as1_post_content_html(self):
    self.assertEqual({
      '$type': 'app.bsky.feed.post',
      'text': 'Some\n_HTML_\n\nok?',
      'fooOriginalText': '<p>Some <br> <em>HTML</em></p>  ok?',
      'createdAt': '2022-01-02T03:04:05.000Z',
    }, self.from_as1({
      'objectType': 'note',
      'content': '<p>Some <br> <em>HTML</em></p>  ok?',
    }))

  def test_from_as1_post_preserve_whitespace_html(self):
    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'text': 'hello\n\n  there\n\nok',
      'fooOriginalText': '<p>hello</p>  there<br><br>ok',
      'createdAt': '2022-01-02T03:04:05.000Z',
    }, self.from_as1({
      'objectType': 'note',
      'content': '<p>hello</p>  there<br><br>ok',
    }))

  def test_from_as1_tag_without_url(self):
    self.assert_equals(POST_BSKY, self.from_as1({
      **POST_AS,
      'tags': [{'objectType': 'mention'}],
    }))

  def test_from_as1_tag_mention_did(self):
    self.assert_equals(POST_BSKY_FACET_MENTION, self.from_as1(NOTE_AS_TAG_MENTION_DID))

  def test_from_as1_tag_mention_did_not_in_content(self):
    self.assert_equals(POST_BSKY, self.from_as1({
      **POST_AS['object'],
      'tags': [TAG_MENTION_DID],
    }))

  def test_from_as1_tag_mention_url(self):
    self.assert_equals(POST_BSKY_FACET_MENTION, self.from_as1(NOTE_AS_TAG_MENTION_URL))

  def test_from_as1_tag_mention_url_not_in_content(self):
    self.assert_equals(POST_BSKY, self.from_as1({
      **POST_AS['object'],
      'tags': [TAG_MENTION_URL],
    }))

  # resolveHandle
  @patch('requests.get', return_value=requests_response({'did': 'did:plc:foo'}))
  def test_from_as1_tag_mention_url_html_link(self, _):
    content = 'foo <a href="https://bsky.app/profile/you.com">@you.com</a> bar'
    self.assert_equals({
      **POST_BSKY_FACET_MENTION,
      'fooOriginalText': content,
      'fooOriginalUrl': 'https://bsky.app/profile/did:alice/post/tid',
    }, self.from_as1({
      **POST_AS['object'],
      'content': content,
    }, client=self.bs), ignore=['createdAt'])

  def test_from_as1_tag_hashtag(self):
    self.assert_equals(POST_BSKY_FACET_HASHTAG, self.from_as1(NOTE_AS_TAG_HASHTAG))

  def test_from_as1_tag_hashtag_guess_index(self):
    note = copy.deepcopy(NOTE_AS_TAG_HASHTAG)
    del note['tags'][0]['startIndex']
    del note['tags'][0]['length']
    del note['tags'][0]['objectType']

    expected = copy.deepcopy(POST_BSKY_FACET_HASHTAG)
    expected['facets'][0]['index']['byteStart'] = 4
    self.assert_equals(expected, self.from_as1(note))

  def test_from_as1_tag_hashtag_html_content_guess_index(self):
    content = '<p>foo <a class="p-category">#hache-☕</a> bar</p>'

    note = copy.deepcopy(NOTE_AS_TAG_HASHTAG)
    note['content'] = content
    del note['tags'][0]['startIndex']
    del note['tags'][0]['length']

    expected = copy.deepcopy(POST_BSKY_FACET_HASHTAG)
    expected['fooOriginalText'] = content
    expected['facets'][0]['index']['byteStart'] = 4
    self.assert_equals(expected, self.from_as1(note))

  def test_from_as1_tag_hashtag_guess_index_case_insensitive(self):
    content = '<p>You can ignore this <a href="https://darkfriend.social/tags/TuneTuesday" class="mention hashtag" rel="tag">#<span>TuneTuesday</span></a> post</p>'

    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'text': 'You can ignore this #TuneTuesday post',
      'fooOriginalText': content,
      'createdAt': '2022-01-02T03:04:05.000Z',
      'facets': [{
        '$type': 'app.bsky.richtext.facet',
        'features': [{
          '$type': 'app.bsky.richtext.facet#tag',
          'tag': 'tunetuesday',
        }],
        'index': {
          'byteStart': 20,
          'byteEnd': 32,
        },
      }],
    }, self.from_as1({
      'objectType': 'note',
      'content': content,
      'tags': [{'displayName': '#tunetuesday'}],
    }))

  def test_from_as1_tag_hashtag_guess_index_punctuation(self):
    content = '<p>Another .<a href="https://darkfriend.social/tags/tunetuesday" class="mention hashtag" rel="tag">#<span>tunetuesday</span></a>! post</p>'

    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'text': 'Another .#tunetuesday! post',
      'fooOriginalText': content,
      'createdAt': '2022-01-02T03:04:05.000Z',
      'facets': [{
        '$type': 'app.bsky.richtext.facet',
        'features': [{
          '$type': 'app.bsky.richtext.facet#tag',
          'tag': 'tunetuesday',
        }],
        'index': {
          'byteStart': 9,
          'byteEnd': 21,
        },
      }],
    }, self.from_as1({
      'objectType': 'note',
      'content': content,
      'tags': [{'displayName': '#tunetuesday'}],
    }))

  def test_from_as1_tag_mention_guess_index(self):
    self.assert_equals(POST_BSKY_FACET_MENTION, self.from_as1({
      'objectType': 'note',
      'content': 'foo @you.com bar',
      'tags': [{
        'objectType': 'mention',
        'url': 'https://bsky.app/profile/did:plc:foo',
        'displayName': 'you.com',
      }],
    }))

  def test_from_as1_tag_mention_html_content_guess_index(self):
    content = '<p>foo <a href="https://bsky.app/...">@you.com</a> bar</p>'
    self.assert_equals({
      **POST_BSKY_FACET_MENTION,
      'fooOriginalText': content,
    }, self.from_as1({
      'objectType': 'note',
      'content': content,
      'tags': [{
        'objectType': 'mention',
        'url': 'https://bsky.app/profile/did:plc:foo',
        'displayName': 'you.com',
      }],
    }))

  def test_from_as1_tag_mention_display_name_server_html_content_guess_index(self):
    content = '<p>foo <a href="https://bsky.app/...">@you.com</a> bar</p>'
    self.assert_equals({
      **POST_BSKY_FACET_MENTION,
      'fooOriginalText': content,
    }, self.from_as1({
      'objectType': 'note',
      'content': content,
      'tags': [{
        'objectType': 'mention',
        'url': 'https://bsky.app/profile/did:plc:foo',
        'displayName': '@you.com@server.foo',
      }],
    }))

  def test_from_as1_tag_mention_at_char_html_content_guess_index(self):
    content = '<p>foo <a href="https://bsky.app/...">@you.com</a> bar</p>'

    note = copy.deepcopy(NOTE_AS_TAG_MENTION_URL)
    note['content'] = content
    note['tags'][0]['displayName'] = '@you.com'
    del note['tags'][0]['startIndex']
    del note['tags'][0]['length']
    self.assert_equals({
      **POST_BSKY_FACET_MENTION,
      'fooOriginalText': '<p>foo <a href="https://bsky.app/...">@you.com</a> bar</p>',
    }, self.from_as1(note))

  def test_from_as1_tag_mention_at_beginning(self):
    content = '<p><span class="h-card" translate="no"><a href="https://bsky.brid.gy/r/https://bsky.app/profile/shreyanjain.net" class="u-url mention">@<span>shreyanjain.net</span></a></span> hello there</p>'

    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'createdAt': '2022-01-02T03:04:05.000Z',
      'text': '@shreyanjain.net hello there',
      'fooOriginalText': content,
      'facets': [{
        '$type': 'app.bsky.richtext.facet',
        'features': [{
          '$type': 'app.bsky.richtext.facet#mention',
          'did': 'did:plc:foo',
        }],
        'index': {
          'byteStart': 0,
          'byteEnd': 16,
        },
      }],
    }, self.from_as1({
      'objectType' : 'note',
      'content' : content,
      'tags' : [{
        'objectType': 'mention',
        'displayName': '@shreyanjain.net@bsky.brid.gy',
        'url': 'did:plc:foo',
      }],
    }))

  def test_from_as1_tag_mention_not_bluesky(self):
    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'createdAt': '2022-01-02T03:04:05.000Z',
      'text': 'foo bar',
      'fooOriginalText': 'foo bar',
    }, self.from_as1({
      'objectType': 'note',
      'content': 'foo bar',
      'tags': [{
        'objectType': 'mention',
        'url': 'http://something/else',
      }],
    }))

  def test_from_as1_drop_tag_with_start_past_content_length(self):
    note = copy.deepcopy(NOTE_AS_TAG_HASHTAG)
    note['tags'][0]['startIndex'] = len(note['content']) + 2

    expected = copy.deepcopy(POST_BSKY_FACET_HASHTAG)
    del expected['facets']
    self.assert_equals(expected, self.from_as1(note))

  def test_from_as1_trim_tag_with_end_past_content_length(self):
    note = copy.deepcopy(NOTE_AS_TAG_HASHTAG)
    expected = copy.deepcopy(POST_BSKY_FACET_HASHTAG)
    note['tags'][0]['length'] = 50
    expected['facets'][0]['index']['byteEnd'] = 18
    self.assert_equals(expected, self.from_as1(note))

  def test_from_as1_html_link(self):
    content = 'foo <a href="http://post">ba]r</a> baz'
    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'createdAt': '2022-01-02T03:04:05.000Z',
      'text': 'foo ba]r baz',
      'fooOriginalText': content,
      'facets': [{
        '$type': 'app.bsky.richtext.facet',
        'features': [{
          '$type': 'app.bsky.richtext.facet#link',
          'uri': 'http://post',
        }],
        'index': {
          'byteStart': 4,
          'byteEnd': 8,
        },
      }],
    }, self.from_as1({
      'objectType': 'note',
      'content': content,
    }))

  @patch.dict(LEXRPC_BASE.defs['app.bsky.feed.post']['record']['properties']['text'],
              maxGraphemes=12)
  def test_from_as1_html_omit_link_facet_after_truncation(self):
    content = 'foo bar <a href="http://post">baaaaaaaz</a>'
    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'createdAt': '2022-01-02T03:04:05.000Z',
      'text': 'foo bar […]',
      'fooOriginalText': content,
    }, self.from_as1({
      'objectType': 'note',
      'content': content,
    }))

  def test_from_as1_link_mention_hashtag(self):
    content = 'foo <a href="...">#hache-☕</a> <a href="http://post">bar</a> foo <a href="https://bsky.app/profile/you.com">@you.com</a> baz'

    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'createdAt': '2022-01-02T03:04:05.000Z',
      'text': 'foo #hache-☕ bar foo @you.com baz',
      'fooOriginalText': content,
      'facets': [{
        '$type': 'app.bsky.richtext.facet',
        'features': [{
          '$type': 'app.bsky.richtext.facet#tag',
          'tag': 'hache-☕',
        }],
        'index': {
          'byteStart': 4,
          'byteEnd': 14,
        },
      }, {
        '$type': 'app.bsky.richtext.facet',
        'features': [{
          '$type': 'app.bsky.richtext.facet#mention',
          'did': 'you.com',
        }],
        'index': {
          'byteStart': 23,
          'byteEnd': 31,
        },
      }, {
        '$type': 'app.bsky.richtext.facet',
        'features': [{
          '$type': 'app.bsky.richtext.facet#link',
          'uri': 'http://post',
        }],
        'index': {
          'byteStart': 15,
          'byteEnd': 18,
        },
      }],
    }, self.from_as1({
      'objectType': 'note',
      'content': content,
      'tags': [{
        'objectType': 'hashtag',
        'displayName': 'hache-☕',
      }],
    }))

  def test_from_as1_post_with_image(self):
    expected = copy.deepcopy(POST_BSKY_IMAGES)
    del expected['embed']
    self.assert_equals(expected, self.from_as1(POST_AS_IMAGES))

  def test_from_as1_post_with_image_blobs(self):
    expected = copy.deepcopy(POST_BSKY_IMAGES)
    expected['embed']['images'][0]['image'] = BLOB
    self.assert_equals(expected, self.from_as1(POST_AS_IMAGES, blobs={NEW_BLOB_URL: BLOB}))

  def test_from_as1_post_with_image_subset_of_blobs(self):
    expected = copy.deepcopy(POST_BSKY_IMAGES)
    expected['embed']['images'][0]['image'] = BLOB
    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'text': '',
      'createdAt': '2022-01-02T03:04:05.000Z',
      'embed': {
        '$type': 'app.bsky.embed.images',
        'images': [{
          '$type': 'app.bsky.embed.images#image',
          'alt': '',
          'image': NEW_BLOB,
        }],
      },
    }, self.from_as1({
      'objectType': 'note',
      'image': ['http://pic/1', NEW_BLOB_URL],
    }, blobs={NEW_BLOB_URL: NEW_BLOB}))

  def test_from_as1_post_view_with_image(self):
    expected = copy.deepcopy(POST_VIEW_BSKY_IMAGES)
    del expected['record']['embed']
    expected['record']['fooOriginalUrl'] = 'https://bsky.app/profile/did:alice/post/tid'
    got = self.from_as1(POST_AS_IMAGES, out_type='app.bsky.feed.defs#postView')
    self.assert_equals(expected, got)

  def test_from_as1_object_vs_activity(self):
    obj = {
      'objectType': 'note',
      'content': 'foo',
    }
    activity = {
      'verb': 'post',
      'object': obj,
    }
    self.assert_equals(self.from_as1(obj), self.from_as1(activity))

  def test_from_as1_actor(self):
    expected = {
      '$type': 'app.bsky.actor.profile',
      'displayName': 'Alice',
      'description': 'hi there',
      'fooOriginalDescription': 'hi there',
      'fooOriginalUrl': 'https://alice.com/',
    }
    self.assert_equals(expected, self.from_as1(ACTOR_AS))
    self.assert_equals(expected, self.from_as1(ACTOR_AS, out_type='app.bsky.actor.profile'))

  def test_from_as1_actor_blobs(self):
    self.assert_equals({
      '$type': 'app.bsky.actor.profile',
      'displayName': 'Alice',
      'description': 'hi there',
      'fooOriginalDescription': 'hi there',
      'fooOriginalUrl': 'https://alice.com/',
      'avatar': BLOB,
    }, self.from_as1(ACTOR_AS, blobs={'https://alice.com/alice.jpg': BLOB}))

  def test_from_as1_actor_profileView(self):
    for type in ('app.bsky.actor.defs#profileView',
                 'app.bsky.actor.defs#profileViewBasic',
                 'app.bsky.actor.defs#profileViewDetailed',
                 ):
      self.assert_equals({
        **ACTOR_PROFILE_VIEW_BSKY,
        '$type': type,
      }, self.from_as1(ACTOR_AS, out_type=type))

  def test_from_as1_actor_handle(self):
    for expected, fields in (
        ('', {}),
        ('fooey.bsky.social', {'username': 'fooey.bsky.social'}),
        ('fooey.com', {'username': 'fooey.com', 'url': 'http://my/url', 'id': 'tag:nope'}),
        ('foo.com', {'url': 'http://foo.com'}),
        ('foo.com', {'url': 'http://foo.com/path'}),
    ):
      self.assert_equals(expected, self.from_as1({
        'objectType': 'person',
        **fields,
      }, out_type='app.bsky.actor.defs#profileView')['handle'])

  def test_from_as1_actor_id_not_url(self):
    """Tests error handling when attempting to generate did:web."""
    self.assertEqual('did:web:foo.com', self.from_as1({
      'objectType': 'person',
      'id': 'tag:foo.com,2001:bar',
    }, out_type='app.bsky.actor.defs#profileView')['did'])

  def test_from_as1_actor_description_html(self):
    summary = '<p>Some <br> <em>HTML</em></p>  ok?'
    self.assertEqual({
      '$type': 'app.bsky.actor.profile',
      'description': 'Some\n_HTML_\n\nok?',
      'fooOriginalDescription': summary,
    }, self.from_as1({
      'objectType': 'person',
      'summary': summary,
    }))

  def test_from_as1_actor_description_plain_text(self):
    self.assertEqual({
      '$type': 'app.bsky.actor.profile',
      'description': 'Some\n  plain  text\n\nok?',
      'fooOriginalDescription': 'Some\n  plain  text\n\nok?',
    }, self.from_as1({
      'objectType': 'person',
      'summary': 'Some\n  plain  text\n\nok?',
    }))

  def test_from_as1_composite_url(self):
    self.assertEqual({
      '$type': 'app.bsky.actor.defs#profileView',
      'did': 'did:web:rodentdisco.co.uk',
      'handle': 'rodentdisco.co.uk',
      'fooOriginalUrl': 'https://rodentdisco.co.uk/author/dan/',
    }, self.from_as1({
      'objectType': 'person',
      'url': {
        "displayName": "my web site",
        "value": "https://rodentdisco.co.uk/author/dan/"
      },
    }, out_type='app.bsky.actor.defs#profileView'))

  def test_from_as1_embed(self):
    self.assert_equals(POST_BSKY_EMBED, self.from_as1(POST_AS_EMBED))

  def test_from_as1_embed_out_type_postView(self):
    got = self.from_as1(POST_AS_EMBED, out_type='app.bsky.feed.defs#postView')
    self.assert_equals(POST_VIEW_BSKY_EMBED, got)

  def test_from_as1_facet_link_and_embed(self):
    self.assert_equals({
      **POST_BSKY_EMBED,
      'facets': [FACET_LINK],
    }, self.from_as1({
      **POST_AS_EMBED,
      'tags': [TAG_LINK],
    }))

  def test_from_as1_post_langs(self):
    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'text': 'My original post',
      'langs': ['en'],
      'createdAt': '2022-01-02T03:04:05.000Z',
    }, from_as1({
      'objectType': 'note',
      'content': 'My original post',
      'contentMap': {
        'en': 'My original post',
        'fr': "Mon message d'origine",
      },
    }))

  def test_from_as1_post_langs_none_match_content(self):
    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'text': 'My original post',
      'createdAt': '2022-01-02T03:04:05.000Z',
    }, from_as1({
      'objectType': 'note',
      'content': 'My original post',
      'contentMap': {
        'es': 'Mi mensaje original',
        'fr': "Mon message d'origine",
      },
    }))

  def test_from_as1_article_to_embed(self):
    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'text': '',
      'createdAt': '2022-01-02T03:04:05.000Z',
      'embed': {
        '$type': 'app.bsky.embed.external',
        'external': {
          '$type': 'app.bsky.embed.external#external',
          'uri': 'http://my/article',
          'title': 'My big article',
          'description': 'some long long long text',
        },
      },
    }, from_as1({
      'objectType': 'article',
      'url': 'http://my/article',
      'displayName': 'My big article',
      'content': 'some long long long text',
      'image': 'http://my/pic',
    }))

  def test_from_as1_article_to_embed_with_image_blobs(self):
    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'text': '',
      'createdAt': '2022-01-02T03:04:05.000Z',
      'embed': {
        '$type': 'app.bsky.embed.external',
        'external': {
          '$type': 'app.bsky.embed.external#external',
          'uri': 'http://my/article',
          'title': 'My big article',
          'description': 'some long long long text',
          'thumb': BLOB,
        },
      },
    }, from_as1({
      'objectType': 'article',
      'url': 'http://my/article',
      'displayName': 'My big article',
      'content': 'some long long long text',
      'image': NEW_BLOB_URL,
    }, blobs={NEW_BLOB_URL: BLOB}))

  def test_from_as1_note_display_name_as_embed(self):
    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'text': '',
      'createdAt': '2022-01-02T03:04:05.000Z',
      'embed': {
        '$type': 'app.bsky.embed.external',
        'external': {
          '$type': 'app.bsky.embed.external#external',
          'uri': 'http://my/article',
          'title': 'My big article',
          'description': '',
        },
      },
    }, from_as1({
      'objectType': 'note',
      'url': 'http://my/article',
      'displayName': 'My big article',
    }, as_embed=True))

  def test_from_as1_repost(self):
    self.assert_equals(REPOST_BSKY, self.from_as1(REPOST_AS))

  def test_from_as1_repost_reasonRepost(self):
    got = self.from_as1(REPOST_AS, out_type='app.bsky.feed.defs#reasonRepost')
    self.assert_equals(REPOST_BSKY_REASON, got)

  def test_from_as1_repost_feedViewPost(self):
    got = self.from_as1(REPOST_AS, out_type='app.bsky.feed.defs#feedViewPost')
    self.assert_equals(REPOST_BSKY_FEED_VIEW_POST, got)

  def test_from_as1_repost_convert_bsky_app_url(self):
    repost_as = copy.deepcopy(REPOST_AS)
    del repost_as['object']['id']

    repost_bsky = copy.deepcopy(REPOST_BSKY)
    repost_bsky['subject']['uri'] = 'at://alice.com/app.bsky.feed.post/tid'
    self.assert_equals(repost_bsky, self.from_as1(repost_as))

  @patch('requests.get')
  def test_from_as1_repost_client(self, mock_get):
    mock_get.return_value = requests_response({
      'uri': 'at://did:alice/app.bsky.feed.post/tid',
      'cid': 'my-syd',
      'value': {},
    })

    expected = copy.deepcopy(REPOST_BSKY)
    expected['subject']['cid'] = 'my-syd'
    self.assert_equals(expected, self.from_as1(REPOST_AS, client=self.bs._client))

    self.assert_call(mock_get,
                     'com.atproto.repo.getRecord'
                     '?repo=did%3Aalice&collection=app.bsky.feed.post&rkey=tid')

  def test_from_as1_reply(self):
    self.assert_equals(REPLY_BSKY, self.from_as1(REPLY_AS))
    self.assert_equals(REPLY_BSKY, self.from_as1(REPLY_AS['object']))

  def test_from_as1_reply_to_website(self):
    self.assert_equals(REPLY_BSKY, self.from_as1(REPLY_TO_WEBSITE_AS))
    self.assert_equals(REPLY_BSKY, self.from_as1(REPLY_TO_WEBSITE_AS['object']))
    reply_to_website_at_uri = copy.deepcopy(REPLY_TO_WEBSITE_AS)
    reply_to_website_at_uri['object']['inReplyTo'][2]['url'] = 'at://did:alice/app.bsky.feed.post/parent-tid'
    self.assert_equals(REPLY_BSKY, self.from_as1(reply_to_website_at_uri))

  def test_from_as1_reply_postView(self):
    for input in REPLY_AS, REPLY_AS['object']:
      got = self.from_as1(input, out_type='app.bsky.feed.defs#postView')
      self.assert_equals(REPLY_POST_VIEW_BSKY, got)

  def test_from_as1_reply_convert_bsky_app_url(self):
    reply_as = copy.deepcopy(REPLY_AS)
    reply_as['object']['inReplyTo'] = \
      'https://bsky.app/profile/did:alice/post/parent-tid'
    self.assert_equals(REPLY_BSKY, self.from_as1(reply_as))

  @patch('requests.get')
  def test_from_as1_reply_client(self, mock_get):
    mock_get.return_value = requests_response({
      'uri': 'at://did:alice/app.bsky.feed.post/parent-tid',
      'cid': 'my-syd',
      'value': {},
    })

    expected = copy.deepcopy(REPLY_BSKY)
    expected['reply']['root']['cid'] = expected['reply']['parent']['cid'] = 'my-syd'
    self.assert_equals(expected, self.from_as1(REPLY_AS['object'], client=self.bs._client))

    self.assert_call(mock_get,
                     'com.atproto.repo.getRecord'
                     '?repo=did%3Aalice&collection=app.bsky.feed.post&rkey=parent-tid')

  @patch('requests.get', return_value=requests_response({
    'uri': 'at://did:alice/app.bsky.feed.post/parent-tid',
    'cid': 'my-parent-syd',
    'value': {
      **POST_BSKY,
      'reply': {
        '$type': 'app.bsky.feed.post#replyRef',
        'root': {
          'uri': 'at://did:bob/app.bsky.feed.post/root-tid',
          'cid': 'my-root-syd',
        },
      },
    },
  }))
  def test_from_as1_reply_client_root(self, mock_get):
    self.assert_equals({
      **REPLY_BSKY,
      'reply': {
        '$type': 'app.bsky.feed.post#replyRef',
        'parent': {
          'uri': 'at://did:alice/app.bsky.feed.post/parent-tid',
          'cid': 'my-parent-syd',
        },
        'root': {
          'uri': 'at://did:bob/app.bsky.feed.post/root-tid',
          'cid': 'my-root-syd',
        },
      },
    }, self.from_as1(REPLY_AS['object'], client=self.bs._client))

    self.assert_call(mock_get,
                     'com.atproto.repo.getRecord'
                     '?repo=did%3Aalice&collection=app.bsky.feed.post&rkey=parent-tid')

  def test_from_as1_reply_not_bluesky_atproto(self):
    with self.assertRaises(ValueError):
      self.from_as1({
        'objectType': 'comment',
        'id': 'https://social.atiusamy.com/notes/9vdetlseu2g408ox',
        'inReplyTo': ['https://social.atiusamy.com/notes/9vder4g1u2g408ov'],
      })

  @patch('requests.get')
  def test_from_as1_like_client(self, mock_get):
    mock_get.return_value = requests_response({
      'uri': 'at://did:alice/app.bsky.feed.post/tid',
      'cid': 'my-syd',
      'value': {},
    })

    expected = copy.deepcopy(LIKE_BSKY)
    expected['subject']['cid'] = 'my-syd'
    self.assert_equals(expected, self.from_as1(LIKE_AS, client=self.bs._client))

    self.assert_call(mock_get,
                     'com.atproto.repo.getRecord'
                     '?repo=did%3Aalice&collection=app.bsky.feed.post&rkey=tid')

  def test_from_as1_follow(self):
    self.assertEqual(FOLLOW_BSKY, self.from_as1(FOLLOW_AS))

  def test_from_as1_follow_no_object(self):
    with self.assertRaises(ValueError):
      self.from_as1({
        'objectType': 'activity',
        'verb': 'follow',
        'actor': 'at://did:plc:foo/com.atproto.actor.profile/123',
      })

  def test_from_as1_image_string_id(self):
    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'text': '',
      'createdAt': '2022-01-02T03:04:05.000Z',
    }, self.from_as1({
      'objectType': 'note',
      'image': ['http://foo'],
    }))

  def test_from_as1_rewrite_published_to_createdAt(self):
    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'text': '',
      'createdAt': '2022-01-02T02:01:09.650Z',
    }, self.from_as1({
      'objectType': 'note',
      'published': '  2022-01-02 00:01:09.65-02:00 ',
    }))

  def test_from_as1_rewrite_published_no_timezone(self):
    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'text': '',
      'createdAt': '2022-01-02T00:01:09.000Z',
    }, self.from_as1({
      'objectType': 'note',
      'published': '2022-01-02 00:01:09 ',
    }))

  def test_from_as1_bad_published(self):
    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'text': '',
      'createdAt': '2022-01-02T03:04:05.000Z',
    }, self.from_as1({
      'objectType': 'note',
      'published': 'foo bar',
    }))

  def test_from_as1_block(self):
    self.assert_equals({
      '$type': 'app.bsky.graph.block',
      'subject': 'https://bsky.app/profile/did:eve',
      'createdAt': '2022-01-02T03:04:05.000Z'
    }, self.from_as1({
      'objectType': 'activity',
      'verb': 'block',
      'actor': 'http://alice',
      'object': 'https://bsky.app/profile/did:eve',
    }))

  # https://docs.joinmastodon.org/spec/activitypub/#Flag
  @patch('requests.get', return_value=requests_response({
    'uri': 'at://did:alice/app.bsky.feed.post/tid',
    'cid': 'my-syd',
    'value': {},
  }))
  def test_from_as1_flag(self, _):
    self.assert_equals({
      '$type': 'com.atproto.moderation.createReport#input',
      'reasonType': 'com.atproto.moderation.defs#reasonOther',
      'reason': 'Please take a look at this user and their posts',
      'subject': {
        '$type': 'com.atproto.repo.strongRef',
        'uri': 'at://did:alice/app.bsky.feed.post/tid',
        'cid': 'my-syd',
      },
    }, self.from_as1({
      'objectType': 'activity',
      'verb': 'flag',
      'id': 'http://flag',
      'actor': 'http://alice',
      'object': [
        'https://bsky.app/profile/did:alice/post/tid',
        'http://other/ post',
      ],
      'content': 'Please take a look at this user and their posts',
      # note that this is the user being reported
      'to': 'did:bob',
    }, client=self.bs._client))

  def test_from_as1_collection(self):
    self.assert_equals({
      '$type': 'app.bsky.graph.list',
      'name': 'My stuff',
      'description': 'its gud',
      'purpose': 'app.bsky.graph.defs#curatelist',
      'avatar': BLOB,
      'createdAt': '2001-02-03T04:05:06.000Z',
    }, self.from_as1({
      'objectType': 'collection',
      'id': 'http://list/id',
      'displayName': 'My stuff',
      'summary': 'its gud',
      'totalItems': 3,
      'image': 'https://pic',
      'published': '2001-02-03T04:05:06',
    }, blobs={'https://pic': BLOB}))

  def test_from_as1_add_to_collection(self):
    self.assert_equals({
      '$type': 'app.bsky.graph.listitem',
      'subject': 'did:bob',
      'list': 'at://did:alice/app.bsky.graph.list/tid',
      'createdAt': '2022-01-02T03:04:05.000Z'
    }, self.from_as1({
      'objectType': 'activity',
      'verb': 'add',
      'actor': 'did:alice',
      'object': 'did:bob',
      'target': 'at://did:alice/app.bsky.graph.list/tid',
    }))

  @patch('requests.get', return_value=requests_response({
    'uri': 'at://did:alice/app.bsky.feed.post/tid',
    'cid': 'my-syd',
    'value': {},
  }))
  def test_from_as1_quote_post_with_image(self, mock_get):
    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'text': 'late morning ...',
      'createdAt': '2022-01-02T03:04:05.000Z',
      'embed': {
        '$type': 'app.bsky.embed.recordWithMedia',
        'record': {
          '$type': 'app.bsky.embed.record',
          'record': {
            'uri': 'at://did:alice/app.bsky.feed.post/tid',
            'cid': 'my-syd',
          },
        },
        'media': {
          '$type': 'app.bsky.embed.images',
          'images': [{
            '$type': 'app.bsky.embed.images#image',
            'alt': '',
            'image': NEW_BLOB,
          }],
        },
      },
      'fooOriginalUrl': 'https://orig/post',
    }, self.from_as1({
      'objectType': 'note',
      'id': 'https://orig/post',
      'content': '<p>late morning ...<br><br>RE: </span><a href=\"https://makai.chaotic.ninja/notes/9stkybisvk\">https://makai.chaotic.ninja/notes/9stkybisvk</a></p>',
      'attachments': [{
        'objectType': 'note',
        'url': 'https://bsky.app/profile/did:x/post/yz',
      }],
      'image': [{
        'objectType': 'image',
        'url': NEW_BLOB_URL,
      }],
    }, client=self.bs._client, blobs={NEW_BLOB_URL: NEW_BLOB}),
    ignore=['fooOriginalText'])

    self.assert_call(
      mock_get,
      'com.atproto.repo.getRecord?repo=did%3Ax&collection=app.bsky.feed.post&rkey=yz')

  def test_from_as1_sensitive(self):
    self.assert_equals({
      '$type': 'app.bsky.feed.post',
      'text': '',
      'labels': {
         '$type': 'com.atproto.label.defs#selfLabels',
         'values': [{'val' : 'graphic-media'}],
      },
      'createdAt': '2022-01-02T03:04:05.000Z',
    }, self.from_as1({
      'objectType' : 'note',
      'sensitive': True,
    }))

  def test_maybe_validate_truncate(self):
    short = 'x' * 63
    long = 'x' * 65

    for input, expected in (
      (short, short),
      (long, short + '…'),
      # ('🇨🇾🇬🇭 bytes', '🇨🇾…'),  # TODO
    ):
      self.assertEqual(expected, self.from_as1({
        'objectType': 'person',
        'displayName': input,
      })['displayName'])

  def test_to_as1_profile(self):
    self.assert_equals({
      'objectType': 'person',
      'id': 'did:plc:foo',
      'username': 'han.dull',
      'displayName': 'Alice',
      'summary': 'hi there',
      'image': [{
        'url': NEW_BLOB_URL,
      }, {
        'objectType': 'featured',
        'url': OLD_BLOB_URL,
      }],
      'url': 'https://bsky.app/profile/han.dull',
      'urls': ['https://bsky.app/profile/han.dull', 'https://han.dull/'],
    }, to_as1(ACTOR_PROFILE_BSKY, repo_did='did:plc:foo', repo_handle='han.dull'))

  def test_to_as1_profile_links_in_bio(self):
    self.assert_equals({
      'objectType': 'person',
      'summary': 'one <a href="http://li.nk/foo">li.nk/foo</a> two <a href="http://li.nk">li.nk</a> three <a href="https://www.li.nk/">li.nk</a>',
      'url': 'http://li.nk/foo',
      'urls': ['http://li.nk/foo', 'https://www.li.nk/'],
    }, to_as1({
      '$type': 'app.bsky.actor.profile',
      'description': 'one http://li.nk/foo two li.nk three https://www.li.nk/',
    }))

  def test_to_as1_profile_escape_html_chars(self):
    self.assert_equals({
      'objectType': 'person',
      'summary': 'one &lt;two&gt; &lt;thr&amp;ee&gt;',
    }, to_as1({
      '$type': 'app.bsky.actor.profile',
      'description': 'one <two> <thr&ee>',
    }))

  def test_to_as1_profile_bsky_social_handle_is_not_url(self):
    self.assert_equals({
      'objectType': 'person',
      'username': 'alice.bsky.social',
      'url': 'https://bsky.app/profile/alice.bsky.social',
    }, to_as1({'$type': 'app.bsky.actor.profile'}, repo_handle='alice.bsky.social'))

  def test_to_as1_profile_view(self):
    self.assert_equals({
      **ACTOR_AS,
      'username': 'alice.com',
      'url': 'https://bsky.app/profile/alice.com',
      'urls': ['https://bsky.app/profile/alice.com', 'https://alice.com/'],
      }, to_as1(ACTOR_PROFILE_VIEW_BSKY))

  def test_to_as1_profile_no_repo_did_handle_or_pds(self):
    self.assert_equals({
      'objectType': 'person',
      'displayName': 'Alice',
      'summary': 'hi there',
    }, to_as1(ACTOR_PROFILE_BSKY, repo_did=None, pds='http://foo'))
    self.assert_equals({
      'objectType': 'person',
      'id': 'did:plc:foo',
      'displayName': 'Alice',
      'summary': 'hi there',
    }, to_as1(ACTOR_PROFILE_BSKY, repo_did='did:plc:foo', pds=None))

  def test_to_as1_profile_no_authenticated_label_to_unlisted(self):
    self.assert_equals({
      'objectType': 'person',
      'displayName': 'Alice',
      'summary': 'hi there',
      'to': [{
        'objectType': 'group',
        'alias': '@unlisted',
      }],
    }, to_as1({
      **ACTOR_PROFILE_BSKY,
      'labels' : {
        '$type': 'com.atproto.label.defs#selfLabels',
        'values': [{
          'cts' : '1970-01-01T00:00:00.000Z',
          'neg' : False,
          'src' : 'did:...',
          'uri' : 'at://did:.../app.bsky.actor.profile/self',
          'val' : NO_AUTHENTICATED_LABEL,
        }],
      },
    }))

  def test_to_as1_profileView_no_authenticated_label_to_unlisted(self):
    got = to_as1({
      **ACTOR_PROFILE_VIEW_BSKY,
      'labels': [{
        'val': NO_AUTHENTICATED_LABEL,
      }],
    })
    self.assert_equals([{
      'objectType': 'group',
      'alias': '@unlisted',
    }], got['to'])

  def test_to_as1_post(self):
    self.assert_equals({
      'objectType': 'note',
      'content': 'My original post',
      'published': '2007-07-07T03:04:05.000Z',
    }, to_as1(POST_BSKY))

  def test_to_as1_post_uri(self):
    self.assert_equals({
      'id': 'at://alice.com/app.bsky.feed.post/123',
      'url': 'https://bsky.app/profile/alice.com/post/123',
      'objectType': 'note',
      'content': 'My original post',
      'published': '2007-07-07T03:04:05.000Z',
    }, to_as1(POST_BSKY, uri='at://alice.com/app.bsky.feed.post/123'))

  @skip
  def test_to_as1_post_escape_html_chars(self):
    self.assert_equals({
      'objectType': 'note',
      'summary': 'one &lt;two&gt; &lt;thr&amp;ee&gt;',
    }, to_as1({
      '$type': 'app.bsky.feed.post',
      'text': 'one <two> <thr&ee>',
    }))

  def test_to_as1_post_langs(self):
    self.assert_equals({
      'objectType': 'note',
      'content': 'My original post',
      'contentMap': {
        'en': 'My original post',
        'fr': 'My original post',
      },
    }, to_as1({
      '$type': 'app.bsky.feed.post',
      'text': 'My original post',
      'langs': ['en', 'fr'],
    }))

  def test_to_as1_post_view(self):
    self.assert_equals(POST_AS['object'], to_as1(POST_VIEW_BSKY))

  def test_to_as1_post_with_author(self):
    self.assert_equals(POST_AUTHOR_PROFILE_AS['object'], to_as1(POST_AUTHOR_BSKY))

  def test_to_as1_post_type_kwarg(self):
    post_bsky = copy.deepcopy(POST_AUTHOR_BSKY)
    type = post_bsky.pop('$type')
    del post_bsky['author']['$type']
    self.assert_equals(POST_AUTHOR_PROFILE_AS['object'], to_as1(post_bsky, type=type))

  def test_to_as1_post_with_image_no_repo_did(self):
    self.assert_equals(trim_nulls({
      **POST_AS_IMAGES['object'],
      'id': None,
      'image': None,
      'url': None,
    }), to_as1(POST_BSKY_IMAGES))

  def test_to_as1_post_with_image_repo_did(self):
    self.assert_equals(trim_nulls({
      **POST_AS_IMAGES['object'],
      'id': None,
      'url': None,
      'author': 'did:plc:foo',
    }), to_as1(POST_BSKY_IMAGES, repo_did='did:plc:foo'))

  def test_to_as1_post_with_image_blank_alt_text(self):
    record = copy.deepcopy(POST_BSKY_IMAGES)
    record['embed']['images'][0]['alt'] = ''

    expected = {
      **POST_AS_IMAGES['object'],
      'author': 'did:plc:foo',
      'id': None,
      'url': None,
      'image': [NEW_BLOB_URL],
    }

    self.assert_equals(trim_nulls(expected), to_as1(record, repo_did='did:plc:foo'))

  def test_to_as1_post_view_with_image(self):
    self.assert_equals(POST_AS_IMAGES['object'], to_as1(POST_VIEW_BSKY_IMAGES))

  def test_to_as1_feedViewPost(self):
    expected = copy.deepcopy(POST_AUTHOR_AS['object'])
    expected['author'].update({
      'url': 'https://bsky.app/profile/alice.com',
      'urls': ['https://bsky.app/profile/alice.com', 'https://alice.com/'],
      'username': 'alice.com',
    })
    self.assert_equals(expected, to_as1(POST_FEED_VIEW_BSKY))

  def test_to_as1_reply(self):
    self.assert_equals(trim_nulls({
      **REPLY_AS['object'],
      'id': None,
      'url': None,
    }), to_as1(REPLY_BSKY))

  def test_to_as1_reply_postView(self):
    self.assert_equals(REPLY_AS['object'], to_as1(REPLY_POST_VIEW_BSKY))

  def test_to_as1_repost(self):
    self.assert_equals({
      'objectType': 'activity',
      'verb': 'share',
      'object': 'at://did:alice/app.bsky.feed.post/tid',
      'published': '2022-01-02T03:04:05.000Z',
    }, to_as1(REPOST_BSKY))

  def test_to_as1_repost_uri(self):
    self.assert_equals({
      'objectType': 'activity',
      'verb': 'share',
      'id': 'at://alice.com/app.bsky.feed.repost/123',
      'url': 'https://bsky.app/profile/did:alice/post/tid#reposted_by_alice.com',
      'object': 'at://did:alice/app.bsky.feed.post/tid',
      'published': '2022-01-02T03:04:05.000Z',
    }, to_as1(REPOST_BSKY, uri='at://alice.com/app.bsky.feed.repost/123'))

  def test_to_as1_like_uri(self):
    self.assert_equals(LIKE_AS, to_as1(LIKE_BSKY, uri='at://alice.com/app.bsky.feed.like/123'))

  def test_to_as1_listView(self):
    self.assert_equals({
      'objectType': 'service',
      'displayName': 'Mai Lyst',
      'id': 'at://did:alice/app.bsky.graph.list/987',
      'url': 'https://bsky.app/profile/did:alice/lists/987',
      'summary': 'a lyst',
      'image': 'https://cdn.bsky.app/lyst@jpeg',
      'author': {
        'objectType': 'person',
        'id': 'did:alice',
        'url': 'https://bsky.app/profile/alice.com',
        'urls': ['https://bsky.app/profile/alice.com', 'https://alice.com/'],
        'username': 'alice.com',
        'image': [{'url': 'https://cdn.bsky.app/alice@jpeg'}]
      }
    }, to_as1({
      '$type': 'app.bsky.graph.defs#listView',
      'avatar': 'https://cdn.bsky.app/lyst@jpeg',
      'cid': '',
      'creator': {
        'avatar': 'https://cdn.bsky.app/alice@jpeg',
        'did': 'did:alice',
        'name': 'Alice',
        'handle': 'alice.com',
      },
      'description': 'a lyst',
      'indexedAt': '2023-11-06T21:08:33.376Z',
      'name': 'Mai Lyst',
      'purpose': 'app.bsky.graph.defs#curatelist',
      'uri': 'at://did:alice/app.bsky.graph.list/987',
    }))

  def test_to_as1_missing_objectType(self):
    with self.assertRaises(ValueError):
      to_as1({'foo': 'bar'})

  def test_to_as1_unknown_objectType(self):
    with self.assertRaises(ValueError):
      to_as1({'objectType': 'poll'})

  def test_to_as1_missing_type(self):
    with self.assertRaises(ValueError):
      to_as1({'foo': 'bar'})

  def test_to_as1_unknown_type(self):
    with self.assertRaises(ValueError):
      to_as1({'$type': 'app.bsky.foo'})

  def test_to_as1_embed(self):
    self.assert_equals(trim_nulls({
      **POST_AS_EMBED,
      'id': None,
      'url': None,
    }), to_as1(POST_BSKY_EMBED))

  def test_to_as1_embed_post_view(self):
    self.assert_equals(POST_AS_EMBED, to_as1(POST_VIEW_BSKY_EMBED))

  def test_to_as1_embed_post_view_thumb_url(self):
    post_bsky = copy.deepcopy(POST_VIEW_BSKY_EMBED)
    post_bsky['embed']['external']['thumb'] = 'http://thu/mb'

    post_as = copy.deepcopy(POST_AS_EMBED)
    post_as['attachments'][0]['image'] = 'http://thu/mb'
    self.assert_equals(post_as, to_as1(post_bsky))
    self.assert_equals(post_as, to_as1(post_bsky, repo_did='did:plc:foo',
                                       repo_handle='han.dull'),
                       ignore=['author'])

  def test_to_as1_embed_with_blobs(self):
    post_bsky = copy.deepcopy(POST_BSKY_EMBED)
    post_bsky['embed']['external']['thumb'] = NEW_BLOB

    post_as = copy.deepcopy(POST_AS_EMBED)
    del post_as['id']
    del post_as['url']

    # without repo_did/repo_handle
    self.assert_equals(post_as, to_as1(post_bsky))

    # with repo_did/repo_handle
    post_as['author'] = 'did:plc:foo'
    post_as['attachments'][0]['image'] = NEW_BLOB_URL
    self.assert_equals(
      post_as, to_as1(post_bsky, repo_did='did:plc:foo', repo_handle='han.dull'))

  def test_to_as1_embed_record(self):
    self.assert_equals({
      'objectType': 'note',
      'content': 'something to say',
      'attachments': [{
        'objectType': 'note',
        'id': 'at://did:alice/app.bsky.feed.post/tid',
        'url': 'https://bsky.app/profile/did:alice/post/tid',
      }],
    }, to_as1({
      '$type': 'app.bsky.feed.post',
      'text': 'something to say',
      'embed': {
        '$type': 'app.bsky.embed.record',
        'record': {
          'uri': 'at://did:alice/app.bsky.feed.post/tid',
          'cid': 'my-syd',
        },
      },
    }))

  def test_to_as1_embed_record_with_media(self):
    self.assert_equals({
      'objectType': 'note',
      'content': 'something to say',
      'author': 'did:plc:foo',
      'attachments': [{
        'objectType': 'note',
        'id': 'at://did:alice/app.bsky.feed.post/tid',
        'url': 'https://bsky.app/profile/did:alice/post/tid',
      }],
      'image': [NEW_BLOB_URL],
    }, to_as1({
      '$type': 'app.bsky.feed.post',
      'text': 'something to say',
      'embed': {
        '$type': 'app.bsky.embed.recordWithMedia',
        'record': {
          '$type': 'app.bsky.embed.record',
          'record': {
            'uri': 'at://did:alice/app.bsky.feed.post/tid',
            'cid': 'my-syd',
          },
        },
        'media': {
          '$type': 'app.bsky.embed.images',
          'images': [{
            '$type': 'app.bsky.embed.images#image',
            'alt': '',
            'image': NEW_BLOB,
          }]
        }
      },
    }, repo_did='did:plc:foo'))

  def test_to_as1_embed_block(self):
    self.assertIsNone(to_as1({
      '$type': 'app.bsky.embed.record#viewBlocked',
      'uri': 'unused',
    }))

  def test_to_as1_facet_link_and_embed(self):
    self.assert_equals(trim_nulls({
      **POST_AS_EMBED,
      'id': None,
      'url': None,
      'tags': [TAG_LINK],
    }), to_as1(    {
      **POST_BSKY_EMBED,
      'facets': [FACET_LINK],
    }))

  def test_to_as1_facet_hashtag(self):
    self.assert_equals(NOTE_AS_TAG_HASHTAG, to_as1(POST_BSKY_FACET_HASHTAG))

  def test_to_as1_facet_mention(self):
    expected = copy.deepcopy(NOTE_AS_TAG_MENTION_URL)
    expected['tags'][0]['displayName'] = '@you.com'
    self.assert_equals(expected, to_as1(POST_BSKY_FACET_MENTION),
                       ignore=['published'])

  def test_to_as1_facet_bad_index_inside_unicode_code_point(self):
    # byteStart points into the middle of a Unicode code point
    # https://bsky.app/profile/did:plc:2ythpj4pwwpka2ljkabouubm/post/3kkfszbaiic2g
    # https://discord.com/channels/1097580399187738645/1097580399187738648/1203118842516082848
    content = 'TIL: DNDEBUGはおいそれと外せない（問題が起こるので外そうとしていたけど思い直している）'

    self.assert_equals({
      'objectType': 'note',
      'published': '2007-07-07T03:04:05',
      'content': content,
      'tags': [{
        'objectType': 'article',
        'url': 'https://seclists.org/bugtraq/2018/Dec/46',
      }],
    }, to_as1({
       '$type' : 'app.bsky.feed.post',
       'text' : content,
       'createdAt' : '2007-07-07T03:04:05',
       'facets' : [{
         'features' : [{
           '$type' : 'app.bsky.richtext.facet#link',
           'uri' : 'https://seclists.org/bugtraq/2018/Dec/46',
         }],
         'index' : {
           'byteEnd' : 90,
           'byteStart' : 50,
         },
       }],
    }))

  def test_to_as1_follow(self):
    self.assertEqual(FOLLOW_AS, to_as1(FOLLOW_BSKY, repo_did='did:alice'))

  def test_to_as1_block(self):
    self.assert_equals({
      'objectType': 'activity',
      'verb': 'block',
      'object': 'did:eve',
    }, to_as1({
      '$type': 'app.bsky.graph.block',
      'subject': 'did:eve',
      'createdAt': '2022-01-02T03:04:05.000Z'
    }))

  def test_to_as1_blockedPost(self):
    self.assert_equals({
      'objectType': 'note',
      'id': 'at://did:alice/app.bsky.feed.post/123',
      'url': 'https://bsky.app/profile/did:alice/post/123',
      'author': 'did:alice',
      'blocked': True,
    }, to_as1({
      '$type' : 'app.bsky.feed.defs#blockedPost',
      'uri': 'at://did:alice/app.bsky.feed.post/123',
      'blocked': True,
      'blockedAuthor': {
        'did': 'did:alice',
      },
    }))

  @patch('requests.get', return_value=requests_response({
    'uri': 'at://did:alice/app.bsky.feed.post/tid',
    'cid': 'my-syd',
    'value': {},
  }))
  def test_to_as1_repo_strongRef(self, _):
    self.assert_equals('at://did:alice/app.bsky.feed.post/123', to_as1({
      '$type' : 'com.atproto.repo.strongRef',
      'uri': 'at://did:alice/app.bsky.feed.post/123',
      'cid': 'my-syd',
    }))

  def test_to_as1_repoRef(self):
    self.assert_equals('did:alice', to_as1({
      '$type' : 'com.atproto.admin.defs#repoRef',
      'did': 'did:alice',
    }))

  # https://docs.joinmastodon.org/spec/activitypub/#Flag
  def test_to_as1_createReport(self):
    self.assert_equals({
      'objectType': 'activity',
      'verb': 'flag',
      'actor': 'did:bob',
      'object': 'at://did:alice/app.bsky.feed.post/123',
      'content': 'Other: Please take a look at this user and their posts',
    }, to_as1({
      '$type': 'com.atproto.moderation.createReport#input',
      'reasonType': 'com.atproto.moderation.defs#reasonOther',
      'reason': 'Please take a look at this user and their posts',
      'subject': {
        '$type': 'com.atproto.repo.strongRef',
        'uri': 'at://did:alice/app.bsky.feed.post/123',
        'cid': 'syd',
      },
    }, repo_did='did:bob'))

  def test_to_as1_feed_generator(self):
    self.assert_equals({
      'objectType': 'service',
      'id': 'at://did:foo/app.bsky.feed.generator/123',
      'author': 'did:plc:foo',
      'generator': 'did:web:skyfeed.me',
      'displayName': 'skyfeeeed',
      'summary': 'its-a skyfeed a-me',
      'image': [{
        'url': NEW_BLOB_URL,
      }],
      'published': '2024-01-09T00:22:39.703Z',
      'url': 'https://bsky.app/profile/did:foo/feed/123',
      'urls': [
        'https://bsky.app/profile/did:foo/feed/123',
        'https://skyfeed.me/',
      ],
    }, to_as1({
      '$type': 'app.bsky.feed.generator',
      'did': 'did:web:skyfeed.me',
      'displayName': 'skyfeeeed',
      'description': 'its-a skyfeed a-me',
      'avatar': NEW_BLOB,
      'createdAt': '2024-01-09T00:22:39.703Z',
    }, uri='at://did:foo/app.bsky.feed.generator/123', repo_did='did:plc:foo'))

  def test_to_as1_feed_generator_no_uri_repo_did(self):
    self.assert_equals({
      'objectType': 'service',
      'generator': 'did:web:skyfeed.me',
      'displayName': 'skyfeeeed',
      'published': '2024-01-09T00:22:39.703Z',
      'url': 'https://skyfeed.me/',
    }, to_as1({
      '$type': 'app.bsky.feed.generator',
      'did': 'did:web:skyfeed.me',
      'displayName': 'skyfeeeed',
      'createdAt': '2024-01-09T00:22:39.703Z',
    }))

  def test_to_as1_list(self):
    self.assert_equals({
      'objectType': 'collection',
      'id': 'at://did:foo/app.bsky.graph.list/123',
      'url': 'https://bsky.app/profile/did:foo/lists/123',
      'displayName': 'My stuff',
      'summary': 'its gud',
      'image': NEW_BLOB_URL,
      'published': '2001-02-03T04:05:06.000Z',
    }, to_as1({
      '$type': 'app.bsky.graph.list',
      'name': 'My stuff',
      'description': 'its gud',
      'purpose': 'app.bsky.graph.defs#curatelist',
      'avatar': NEW_BLOB,
      'createdAt': '2001-02-03T04:05:06.000Z',
    }, uri='at://did:foo/app.bsky.graph.list/123', repo_did='did:plc:foo'))

  def test_to_as1_listitem(self):
    self.assert_equals({
      'objectType': 'activity',
      'verb': 'add',
      'id': 'at://did:foo/app.bsky.graph.listitem/123',
      'actor': 'did:alice',
      'object': 'did:bob',
      'target': 'at://did:alice/app.bsky.graph.list/tid',
      'published': '2001-02-03T04:05:06.000Z',
    }, to_as1({
      '$type': 'app.bsky.graph.listitem',
      'subject': 'did:bob',
      'list': 'at://did:alice/app.bsky.graph.list/tid',
      'createdAt': '2001-02-03T04:05:06.000Z',
    }, uri='at://did:foo/app.bsky.graph.listitem/123', repo_did='did:alice'))

  def test_blob_to_url(self):
    self.assertIsNone(blob_to_url(blob={'foo': 'bar'}, repo_did='x', pds='y'))
    self.assertEqual(NEW_BLOB_URL, blob_to_url(blob=NEW_BLOB,
                                               repo_did='did:plc:foo'))
    self.assertEqual(OLD_BLOB_URL, blob_to_url(blob=OLD_BLOB,
                                               repo_did='did:plc:foo'))

  def test_to_as1_sensitive_content_warning(self):
    self.assert_equals({
      'objectType' : 'note',
      'sensitive': True,
      'summary': f'Sexually suggestive<br>Adult content',
    }, to_as1({
      '$type': 'app.bsky.feed.post',
      'labels' : {
         '$type' : 'com.atproto.label.defs#selfLabels',
         'values' : [
           {'val' : 'sexual'},
           {'val' : 'porn'},
         ],
      },
    }))

  def test_constructor_access_token(self):
    bs = Bluesky('handull', access_token='towkin')
    self.assertEqual({
      'accessJwt': 'towkin',
      'refreshJwt': None,
    }, bs.client.session)

  @patch('requests.post')
  def test_constructor_app_password(self, mock_post):
    session = {
      'handle': 'real.han.dull',
      'did': 'did:plc:me',
      'accessJwt': 'towkin',
      'refreshJwt': 'reephrush',
    }
    mock_post.return_value = requests_response(session)

    bs = Bluesky('handull', app_password='pazzwurd')
    bs.client  # trigger login
    self.assertEqual('real.han.dull', bs.handle)
    self.assertEqual('did:plc:me', bs.did)
    self.assertEqual(session, bs.client.session)

    mock_post.assert_called_once_with(
      'https://bsky.social/xrpc/com.atproto.server.createSession',
      json={'identifier': 'handull', 'password': 'pazzwurd'},
      data=None,
      headers={
        'Content-Type': 'application/json',
        'User-Agent': util.user_agent,
      },
    )

  @patch('requests.get')
  def test_get_activities_friends(self, mock_get):
    mock_get.return_value = requests_response({
      'cursor': 'timestamp::cid',
      'feed': [POST_FEED_VIEW_BSKY, REPOST_BSKY_FEED_VIEW_POST],
    })

    expected_repost = copy.deepcopy(REPOST_AS)
    expected_repost['actor']['username'] = 'bob.com'
    self.assert_equals([POST_AUTHOR_PROFILE_AS, expected_repost],
                       self.bs.get_activities(group_id=FRIENDS))

    self.assert_call(mock_get, 'app.bsky.feed.getTimeline')

  @patch('requests.get')
  def test_get_activities_activity_id(self, mock_get):
    mock_get.return_value = requests_response({
      'thread': THREAD_BSKY,
    })

    self.assert_equals([POST_AUTHOR_PROFILE_AS],
                       self.bs.get_activities(activity_id='at://id'))
    self.assert_call(mock_get, 'app.bsky.feed.getPostThread?uri=at%3A%2F%2Fid&depth=1')

  def test_get_activities_bad_activity_id(self):
    with self.assertRaises(ValueError):
      self.bs.get_activities(activity_id='not_at_uri')

  @patch('requests.get')
  def test_get_activities_self_user_id(self, mock_get):
    mock_get.return_value = requests_response({
      'cursor': 'timestamp::cid',
      'feed': [POST_AUTHOR_BSKY],
    })

    self.assert_equals([POST_AUTHOR_PROFILE_AS],
                       self.bs.get_activities(group_id=SELF, user_id='alice.com'))
    self.assert_call(mock_get, 'app.bsky.feed.getAuthorFeed?actor=alice.com')

  @patch('requests.get')
  def test_get_activities_prefers_did(self, mock_get):
    mock_get.return_value = requests_response({
      'feed': [],
    })

    self.bs.did = 'did:alice'
    self.assert_equals([], self.bs.get_activities(group_id=SELF))
    self.assert_call(mock_get, 'app.bsky.feed.getAuthorFeed?actor=did%3Aalice')

  @patch('requests.get')
  def test_get_activities_with_likes(self, mock_get):
    mock_get.side_effect = [
      requests_response({
        'cursor': 'timestamp::cid',
        'feed': [POST_FEED_VIEW_WITH_LIKES_BSKY],
      }),
      requests_response({
        'cursor': 'timestamp::cid',
        'uri': 'at://did/app.bsky.feed.post/tid',
        'likes': [GET_LIKES_LIKE_BSKY]
      })
    ]

    cache = {}
    self.assert_equals(
      [POST_AUTHOR_PROFILE_WITH_LIKES_AS],
      self.bs.get_activities(fetch_likes=True, cache=cache)
    )
    self.assert_call(mock_get, 'app.bsky.feed.getTimeline')
    self.assert_call(mock_get,
        'app.bsky.feed.getLikes?uri=at%3A%2F%2Fdid%3Aalice%2Fapp.bsky.feed.post%2Ftid')
    self.assert_equals(1, cache.get('ABL at://did:alice/app.bsky.feed.post/tid'))

  @patch('requests.get')
  def test_get_activities_with_reposts(self, mock_get):
    mock_get.side_effect = [
      requests_response({
        'cursor': 'timestamp::cid',
        'feed': [POST_FEED_VIEW_WITH_REPOSTS_BSKY],
      }),
      requests_response({
        'cursor': 'timestamp::cid',
        'uri': 'at://did/app.bsky.feed.post/tid',
        'repostedBy': [ACTOR_PROFILE_VIEW_BSKY]
      })
    ]

    cache = {}
    self.assert_equals(
      [POST_AUTHOR_PROFILE_WITH_REPOSTS_AS],
      self.bs.get_activities(fetch_shares=True, cache=cache)
    )
    self.assert_call(mock_get, 'app.bsky.feed.getTimeline')
    self.assert_call(mock_get,
        'app.bsky.feed.getRepostedBy?uri=at%3A%2F%2Fdid%3Aalice%2Fapp.bsky.feed.post%2Ftid')
    self.assert_equals(1, cache.get('ABRP at://did:alice/app.bsky.feed.post/tid'))

  @patch('requests.get')
  def test_get_activities_include_shares(self, mock_get):
    mock_get.return_value = requests_response({
      'cursor': 'timestamp::cid',
      'feed': [POST_FEED_VIEW_BSKY, REPOST_BSKY_FEED_VIEW_POST],
    })

    self.assert_equals(
      [POST_AUTHOR_PROFILE_AS, REPOST_PROFILE_AS],
      self.bs.get_activities(include_shares=True)
    )

  @patch('requests.get')
  def test_get_activities_with_replies(self, mock_get):
    mock_get.side_effect = [
      requests_response({
        'cursor': 'timestamp::cid',
        'feed': [POST_FEED_VIEW_WITH_REPLIES_BSKY],
      }),
      requests_response({
        'thread': THREAD_BSKY,
      })
    ]

    cache = {}
    self.assert_equals([THREAD_AS],
                       self.bs.get_activities(fetch_replies=True, cache=cache))
    self.assert_call(mock_get,'app.bsky.feed.getTimeline')
    self.assert_call(mock_get,
        'app.bsky.feed.getPostThread?uri=at%3A%2F%2Fdid%3Aalice%2Fapp.bsky.feed.post%2Ftid')
    self.assert_equals(1, cache.get('ABR at://did:alice/app.bsky.feed.post/tid'))

  @patch('requests.get')
  def test_get_activities_replies_not_found_blocked(self, mock_get):
    mock_get.side_effect = [
      requests_response({
        # 'cursor': 'timestamp::cid',
        'feed': [POST_FEED_VIEW_WITH_REPLIES_BSKY],
      }),
      requests_response({
        'thread': {
          **THREAD_BSKY,
          'replies': [{
            '$type': 'app.bsky.feed.defs#notFoundPost',
            'uri': 'at://did:bob/app.bsky.feed.post/reply',
            'notFound': True,
          }, {
            '$type': 'app.bsky.feed.defs#blockedPost',
            'uri': 'at://did:eve/app.bsky.feed.post/reply',
            'blocked': True,
            'author': {
              '$type': 'app.bsky.feed.defs#blockedAuthor',
              'did': 'did:eve',
            },
          }],
        },
      }),
    ]

    expected = copy.deepcopy(THREAD_AS)
    expected['object']['replies'] = {
      'items': [{
        'objectType': 'note',
        'id': 'tag:bsky.app:at://did:eve/app.bsky.feed.post/reply',
        'url': 'https://bsky.app/profile/did:eve/post/reply',
        'blocked': True,
      }],
    }
    self.assert_equals([expected], self.bs.get_activities(fetch_replies=True))

  @patch('requests.get')
  def test_get_actor(self, mock_get):
    mock_get.return_value = requests_response({
      **ACTOR_PROFILE_VIEW_BSKY,
      '$type': 'app.bsky.actor.defs#profileViewDetailed',
    })

    self.assert_equals({
      **ACTOR_AS,
      'url': 'https://bsky.app/profile/alice.com',
      'urls': ['https://bsky.app/profile/alice.com', 'https://alice.com/'],
      'username': 'alice.com',
    }, self.bs.get_actor(user_id='me.com'))
    self.assert_call(mock_get, 'app.bsky.actor.getProfile?actor=me.com')

  @patch('requests.get')
  def test_get_actor_default(self, mock_get):
    mock_get.return_value = requests_response({
      **ACTOR_PROFILE_VIEW_BSKY,
      '$type': 'app.bsky.actor.defs#profileViewDetailed',
    })

    self.assert_equals({
      **ACTOR_AS,
      'url': 'https://bsky.app/profile/alice.com',
      'urls': ['https://bsky.app/profile/alice.com', 'https://alice.com/'],
      'username': 'alice.com',
    }, self.bs.get_actor())
    self.assert_call(mock_get, 'app.bsky.actor.getProfile?actor=did%3Adyd')

  @patch('requests.get')
  def test_get_comment(self, mock_get):
    mock_get.return_value = requests_response({
      'thread': THREAD_BSKY,
    })

    self.assert_equals(POST_AUTHOR_PROFILE_AS['object'],
                       self.bs.get_comment(comment_id='at://id'))
    self.assert_call(mock_get, 'app.bsky.feed.getPostThread?uri=at%3A%2F%2Fid&depth=1')

  def test_post_id(self):
    for input, expected in [
        (None, None),
        ('', None),
        ('abc', None),
        ('http://foo', None),
        ('https://bsky.app/profile/foo', None),
        ('at://did:plc:foo', None),
        ('at://did/post/tid', 'at://did/post/tid'),
        ('https://bsky.app/profile/did/post/tid', 'at://did/app.bsky.feed.post/tid'),
    ]:
      with self.subTest(input=input):
        self.assertEqual(expected, self.bs.post_id(input))

  @patch.dict(LEXRPC_BASE.defs['app.bsky.feed.post']['record']['properties']['text'],
              maxGraphemes=20)
  def test_preview_post(self):
    for content, expected in (
        ('foo ☕ bar', 'foo ☕ bar'),
        ('too long, will be ellipsized', 'too long, will […]'),
        ('<p>foo ☕ <a>bar</a></p>', 'foo ☕ bar'),
        # TODO
        # ('#Asdf ☕ bar', '<a href="http://foo.com/tags/Asdf">#Asdf</a> ☕ bar'),
        # @-mention
        # ('foo ☕ @alice.com', 'foo ☕ <a href="http://bsky.app/profile/alice.com">@alice.com</a>'),
        # ('link asdf.com', 'link <a href="http://asdf.com">asdf.com</a>'),
      ):
      with self.subTest(content=content, expected=expected):
        obj = copy.deepcopy(POST_AS['object'])
        obj['content'] = content
        got = self.bs.preview_create(obj)
        self.assertEqual('<span class="verb">post</span>:', got.description)
        self.assertEqual(expected, got.content)

  @patch('requests.post')
  def test_create_post(self, mock_post):
    at_uri = 'at://did:me/app.bsky.feed.post/abc123'
    mock_post.return_value = requests_response({'uri': at_uri})

    post_as = {
      **POST_AS['object'],
      'url': 'http://orig',
    }
    self.assert_equals({
      'id': at_uri,
      'url': 'https://bsky.app/profile/handull/post/abc123',
    }, self.bs.create(post_as, include_link=INCLUDE_LINK).content)

    post_bsky = {
      **POST_BSKY,
      'text': POST_BSKY['text'] + ' (http://orig)',
      'facets': [{
        '$type': 'app.bsky.richtext.facet',
        'features': [{
          '$type': 'app.bsky.richtext.facet#link',
          'uri': 'http://orig',
        }],
        'index': {
          'byteStart': 18,
          'byteEnd': 29,
        },
      }],
    }
    del post_bsky['fooOriginalText']
    del post_bsky['fooOriginalUrl']

    self.assert_call(mock_post, 'com.atproto.repo.createRecord', json={
      'repo': self.bs.did,
      'collection': 'app.bsky.feed.post',
      'record': post_bsky,
    })

  @patch('requests.post')
  @patch('requests.get')
  def test_create_reply(self, mock_get, mock_post):
    post_at_uri = 'at://did:alice/app.bsky.feed.post/parent-tid'
    for in_reply_to in [post_at_uri,
                        'https://bsky.app/profile/did:alice/post/parent-tid']:
      with self.subTest(in_reply_to=in_reply_to):
        mock_get.return_value = requests_response({
          'uri': post_at_uri,
          'cid': 'my-syd',
        })
        reply_at_uri = 'at://did:me/app.bsky.feed.post/abc123'
        mock_post.return_value = requests_response({'uri': reply_at_uri})

        self.assert_equals({
          'id': reply_at_uri,
          'url': 'https://bsky.app/profile/handull/post/abc123',
        }, self.bs.create({
          **REPLY_AS['object'],
          'inReplyTo': in_reply_to,
        }).content)

        reply_bsky = copy.deepcopy(REPLY_BSKY)
        reply_bsky['reply']['root']['cid'] = \
          reply_bsky['reply']['parent']['cid'] = 'my-syd'
        del reply_bsky['fooOriginalText']
        del reply_bsky['fooOriginalUrl']
        self.assert_call(mock_post, 'com.atproto.repo.createRecord', json={
          'repo': self.bs.did,
          'collection': 'app.bsky.feed.post',
          'record': reply_bsky,
        })

  def test_preview_reply(self):
    for in_reply_to in ['at://did:alice/app.bsky.feed.post/parent-tid',
                        'https://bsky.app/profile/did:alice/post/parent-tid']:
      with self.subTest(in_reply_to=in_reply_to):
        preview = self.bs.preview_create({
          **REPLY_AS['object'],
          'inReplyTo': in_reply_to,
        })
        self.assertIn('<span class="verb">reply</span> to <a href="https://bsky.app/profile/did:alice/post/parent-tid">this post</a>:', preview.description)
        self.assert_equals('I hereby reply to this', preview.content)

  # TODO: requires detecting and discarding non-atproto inReplyTo in from_as1
  # @patch('requests.post')
  # def test_create_non_atproto_reply(self, mock_post):
  #   at_uri = 'at://did:me/app.bsky.feed.post/abc123'
  #   mock_post.return_value = requests_response({'uri': at_uri})

  #   self.assert_equals({
  #     'id': at_uri,
  #     'url': 'https://bsky.app/profile/handull/post/abc123',
  #   }, self.bs.create({
  #     'objectType': 'note',
  #     'content': 'I hereby reply to this',
  #     'inReplyTo': 'https://twitter.com/ugh',
  #   }).content)

  #   self.assert_call(mock_post, 'com.atproto.repo.createRecord', json={
  #     'repo': self.bs.did,
  #     'collection': 'app.bsky.feed.post',
  #     'record': POST_BSKY,
  #   })

  #   got = self.bs.create({
  #     'content': 'foo ☕ bar',
  #     'inReplyTo': [{'url': 'http://not/atproto'}],
  #   })
  #   self.assert_equals(POST, got.content, got)

  @patch('requests.post')
  @patch('requests.get')
  def test_create_like(self, mock_get, mock_post):
    mock_get.return_value = requests_response({
      'uri': LIKE_AS['object'],
      'cid': 'my-syd',
    })
    mock_post.return_value = requests_response({'uri': LIKE_AS['id']})

    self.assert_equals({
      'id': LIKE_AS['id'],
      'url': 'https://bsky.app/profile/did:alice/post/tid/liked-by',
    }, self.bs.create(LIKE_AS).content)

    like_bsky = copy.deepcopy(LIKE_BSKY)
    like_bsky['subject']['cid'] = 'my-syd'
    self.assert_call(mock_post, 'com.atproto.repo.createRecord', json={
      'repo': self.bs.did,
      'collection': 'app.bsky.feed.like',
      'record': like_bsky,
    })

  def test_preview_like(self):
    preview = self.bs.preview_create(LIKE_AS)
    self.assertIn('<span class="verb">like</span> <a href="https://bsky.app/profile/did:alice/post/tid">this post</a>.', preview.description)

  @patch('requests.post')
  @patch('requests.get')
  def test_create_repost(self, mock_get, mock_post):
    mock_get.return_value = requests_response({
      'uri': REPOST_AS['object']['id'],
      'cid': 'my-syd',
    })
    at_uri = 'at://alice.com/app.bsky.feed.repost/123'
    mock_post.return_value = requests_response({'uri': at_uri})

    self.assert_equals({
      'id': at_uri,
      'url': 'https://bsky.app/profile/did:alice/post/tid/reposted-by',
    }, self.bs.create(REPOST_AS).content)

    repost_bsky = copy.deepcopy(REPOST_BSKY)
    repost_bsky['subject']['cid'] = 'my-syd'
    self.assert_call(mock_post, 'com.atproto.repo.createRecord', json={
      'repo': self.bs.did,
      'collection': 'app.bsky.feed.repost',
      'record': repost_bsky,
    })

  def test_preview_repost(self):
    preview = self.bs.preview_create(REPOST_AS)
    self.assertIn('<span class="verb">repost</span> <a href="https://bsky.app/profile/alice.com/post/tid">this post</a>.', preview.description)

  def test_preview_with_media(self):
    preview = self.bs.preview_create(POST_AS_IMAGES['object'])
    self.assertEqual('<span class="verb">post</span>:', preview.description)
    self.assertEqual(
      f'My original post<br /><br /><img src="{NEW_BLOB_URL}" alt="my alt text" />',
      preview.content)

  @patch('requests.post')
  @patch('requests.get')
  def test_create_with_media(self, mock_get, mock_post):
    mock_get.return_value = requests_response(
      'pic data', headers={'Content-Type': 'my/pic'})

    at_uri = 'at://did:me/app.bsky.feed.post/abc123'
    mock_post.side_effect = [
      requests_response({'blob': NEW_BLOB}),
      requests_response({'uri': at_uri}),
    ]

    self.assert_equals({
      'id': at_uri,
      'url': 'https://bsky.app/profile/handull/post/abc123',
    }, self.bs.create(POST_AS_IMAGES['object']).content)

    mock_get.assert_called_with(NEW_BLOB_URL, stream=True, timeout=HTTP_TIMEOUT,
                                headers={'User-Agent': util.user_agent})
    mock_post.assert_any_call(
      'https://bsky.social/xrpc/com.atproto.repo.uploadBlob',
      json=None,
      data=ANY,
      headers={
        'Authorization': 'Bearer towkin',
        'Content-Type': 'my/pic',
        'User-Agent': util.user_agent,
      })
    # lexrpc.Client passes a BytesIO as data. sadly requests reads from that
    # buffer and then closes it, so we can't check its contents.
    # self.assertEqual(b'pic data', repr(mock_post.call_args_list[0][1]['data']))

    expected = copy.deepcopy(POST_BSKY_IMAGES)
    del expected['fooOriginalText']
    del expected['fooOriginalUrl']
    self.assert_call(mock_post, 'com.atproto.repo.createRecord', json={
      'repo': self.bs.did,
      'collection': 'app.bsky.feed.post',
      'record': expected,
    })

  @patch('requests.post')
  def test_preview_with_too_many_media(self, mock_post):
    image_urls = [f'http://my/picture/{i}' for i in range(MAX_IMAGES + 1)]
    obj = {
      'objectType': 'note',
      'image': [{'url': url} for url in image_urls],
      # duplicate images to check that they're de-duped
      'attachments': [{'objectType': 'image', 'url': url} for url in image_urls],
    }

    preview = self.bs.preview_create(obj)
    self.assertEqual('<span class="verb">post</span>:', preview.description)
    self.assertEqual("""\
<br /><br />\
<img src="http://my/picture/0" alt="" /> \
&nbsp; <img src="http://my/picture/1" alt="" /> \
&nbsp; <img src="http://my/picture/2" alt="" /> \
&nbsp; <img src="http://my/picture/3" alt="" />""",
                     preview.content)

  # TODO
  # @patch('requests.post')
  # def test_create_with_too_many_media(self, mock_post):
  #   at_uri = 'at://did:me/app.bsky.feed.post/abc123'
  #   mock_post.side_effect = [
  #     requests_response({'blob': NEW_BLOB}),
  #     requests_response({'uri': at_uri}),
  #   ]

  #   image_urls = [f'http://my/picture/{i}' for i in range(MAX_IMAGES + 1)]
  #   obj = {
  #     'objectType': 'note',
  #     'image': [{'url': url} for url in image_urls],
  #     # duplicate images to check that they're de-duped
  #     'attachments': [{'objectType': 'image', 'url': url} for url in image_urls],
  #   }

  #   for i, url in enumerate(image_urls[:-1]):
  #     self.expect_requests_get(f'http://my/picture/{i}', 'pic')
  #     self.expect_post(API_MEDIA, {'id': str(i + 1)}, files={'file': b'pic'}, data={})

  #   self.expect_post(API_STATUSES, json={
  #     'status': '',
  #     'media_ids': ['0', '1', '2', '3'],
  #   }, response=POST)
  #   self.mox.ReplayAll()
  #   result = self.bs.create(obj)
  #   self.assert_equals(POST, result.content, result)

  @patch('requests.post')
  def test_create_bookmark(self, mock_post):
    at_uri = 'at://did:me/app.bsky.feed.post/abc123'
    mock_post.return_value = requests_response({'uri': at_uri})

    activity = {
      'objectType': 'activity',
      'verb': 'post',
      'content': 'foo ☕ bar',
      'object': {
        'objectType': 'bookmark',
        'targetUrl': 'https://example.com/foo',
      }
    }
    self.assert_equals({
      'id': at_uri,
      'url': 'https://bsky.app/profile/handull/post/abc123',
    }, self.bs.create(activity).content)

    self.assert_call(mock_post, 'com.atproto.repo.createRecord', json={
      'repo': self.bs.did,
      'collection': 'app.bsky.feed.post',
      'record': {
        '$type': 'app.bsky.feed.post',
        'text': 'foo ☕ bar',  # TODO \n\nhttps://example.com/foo',
        'createdAt': '2022-01-02T03:04:05.000Z',
      },
      # TODO
      # 'facets': [{
      #   '$type': 'app.bsky.richtext.facet',
      #   'features': [{
      #     '$type': 'app.bsky.richtext.facet#link',
      #     'uri': 'https://example.com/foo',
      #   }],
      #   'index': {
      #     'byteStart': 13,
      #     'byteEnd': 36,
      #   },
      # }],
    })

  @patch('requests.post')
  @patch('requests.get', return_value=requests_response({'did': 'did:plc:foo'}))
  def test_create_mention(self, _, mock_post):
    at_uri = 'at://did:me/app.bsky.feed.post/abc123'
    mock_post.return_value = requests_response({'uri': at_uri})

    content = 'foo <a href="https://bsky.app/profile/you.com">@you.com</a> bar'
    self.assert_equals({
      'id': at_uri,
      'url': 'https://bsky.app/profile/handull/post/abc123',
    }, self.bs.create({
      'objectType': 'note',
      'content': content,
    }).content)

    self.assert_call(mock_post, 'com.atproto.repo.createRecord', json={
      'repo': self.bs.did,
      'collection': 'app.bsky.feed.post',
      'record': {
        '$type': 'app.bsky.feed.post',
        'text': 'foo @you.com bar',
        'createdAt': '2022-01-02T03:04:05.000Z',
        'facets': [{
          '$type': 'app.bsky.richtext.facet',
          'features': [{
            '$type': 'app.bsky.richtext.facet#mention',
            'did': 'did:plc:foo',
          }],
          'index': {
            'byteStart': 4,
            'byteEnd': 12,
          },
        }],
      },
    })

  @patch('requests.post')
  def test_delete(self, mock_post):
    mock_post.return_value = requests_response({})

    got = self.bs.delete('at://did:dyd/app.bsky.feed.post/abc123')
    self.assert_call(mock_post, 'com.atproto.repo.deleteRecord', json={
      'repo': self.bs.did,
      'collection': 'app.bsky.feed.post',
      'rkey': 'abc123',
    })

  def test_preview_delete(self):
    got = self.bs.preview_delete('at://did:dyd/app.bsky.feed.post/abc123')
    self.assertIn('<span class="verb">delete</span> <a href="https://bsky.app/profile/did:dyd/post/abc123">this</a>.', got.description)
    self.assertIsNone(got.error_plain)
    self.assertIsNone(got.error_html)
