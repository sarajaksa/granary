"""Unit tests for jsonfeed.py."""
from oauth_dropins.webutil import testutil

from ..jsonfeed import activities_to_jsonfeed, jsonfeed_to_activities


class JsonFeedTest(testutil.TestCase):

  def test_activities_to_jsonfeed_empty(self):
    self.assert_equals({
      'version': 'https://jsonfeed.org/version/1',
      'title': 'JSON Feed',
    }, activities_to_jsonfeed([], {}))

  def test_activities_to_jsonfeed_extra_fields(self):
    self.assert_equals({
      'version': 'https://jsonfeed.org/version/1',
      'title': 'a something',
      'feed_url': 'http://a/feed',
      'home_page_url': 'http://a/home',
    }, activities_to_jsonfeed(
      [], {}, title='a something', feed_url='http://a/feed',
      home_page_url='http://a/home'))

  def test_activities_to_jsonfeed_skip_people(self):
    self.assert_equals({
      'version': 'https://jsonfeed.org/version/1',
      'title': 'JSON Feed',
    }, activities_to_jsonfeed([{
      'objectType': 'person',
      'displayName': 'somebody',
    }], {}))

  def test_activities_to_jsonfeed_no_content(self):
    self.assert_equals({
      'version': 'https://jsonfeed.org/version/1',
      'title': 'JSON Feed',
      'items': [{
        'image': 'http://no/content',
        'content_text': '',
      }],
    }, activities_to_jsonfeed([{
      'image': [{'url': 'http://no/content'}],
    }], {}))

  def test_activities_to_jsonfeed_name_is_not_title(self):
    self.assert_equals([{
      'content_html': 'a microblog post',
    }], activities_to_jsonfeed([{
      'content': 'a microblog post',
      'displayName': 'a microblog post',
    }], {})['items'])

  def test_activities_to_jsonfeed_image_attachment(self):
    self.assert_equals([{
      'content_html': '\n<p>\n<img class="u-photo" src="http://pict/ure.jpg" alt="" />\n</p>',
      'attachments': [{
        'url': 'http://pict/ure.jpg',
        'mime_type': 'image/jpeg',
      }],
    }], activities_to_jsonfeed([{
      'attachments': [{'image': {'url': 'http://pict/ure.jpg'}}],
    }], {})['items'])

  def test_activities_to_jsonfeed_ignore_other_attachment_types(self):
    self.assert_equals([{
      'content_html': '\n<p>\n<a class="link" href="http://some/one">\n</a>\n</p>'
    }], activities_to_jsonfeed([{
      'attachments': [{
        'url': 'http://quoted/tweet',
        'objectType': 'note',
      }, {
        'url': 'http://some/one',
        'objectType': 'person',
      }],
    }], {})['items'])

  def test_activities_to_jsonfeed_attachment_without_url(self):
    self.assert_equals([{'content_text': ''}], activities_to_jsonfeed([{
      'attachments': [{
        'content': 'foo',
        'objectType': 'note',
      }],
    }], {})['items'])

  def test_activities_to_jsonfeed_image_not_dict(self):
    """
    https://console.cloud.google.com/errors/detail/CMnZ6r6AlaXUSg;time=P30D?project=granary-demo
    """
    self.assert_equals([{'content_html': """
<p>
<img class="u-photo" src="https://att/image" alt="" />
</p>"""}], activities_to_jsonfeed([{
      'attachments': [{
        'image': 'https://att/image',
      }],
    }], {})['items'])

  def test_activities_to_jsonfeed_not_list(self):
    for bad in None, 3, 'asdf', {'not': 'a list'}:
      with self.assertRaises(TypeError):
        activities_to_jsonfeed(bad)

  def test_activities_to_jsonfeed_string_object_actor(self):
    self.assert_equals([{
      'id': 'http://example.com/original/post',
      'content_text': '',
    }], activities_to_jsonfeed([{
      'objectType': 'activity',
      'verb': 'like',
      'object': 'http://example.com/original/post',
      'actor': 'http://example.com/author-456'
    }])['items'])

  def test_jsonfeed_to_activities_attachment_extra_list(self):
    """Originally seen in:
    https://console.cloud.google.com/errors/CPyvpeH077rvIg
    https://www.macstories.net/feed/json
    """
    with self.assertRaises(ValueError):
      jsonfeed_to_activities({
        'items': [{
          'attachments': [[{'content': 'foo'}]],
        }]
      })

  def test_not_jsonfeed(self):
    """Based on this JSON, which isn't JSON Feed:

    http://blogs.adobe.com/adobemarketingcloudjapan/feed-json-adobemarketingcloudjapan/

    https://console.cloud.google.com/errors/2337929195804363905
    """
    with self.assertRaises(ValueError):
      jsonfeed_to_activities([{
        'id': 7,
        'date': 'July 11, 2017',
        'title': 'Adobe Digital Insights: 音声認識機能は次の破壊的技術革新となるか',
        'catname': 'Adobe Digital Insights',
        'tags': 'ADI',
        'description': '音声認識機能は新しいコンセプトではありませんが、人工知能 (AI) とマシンラーニングの進歩により、近年採用される機会が増えています。アドビが公開したAdobe Digital Insights (ADI) の最新のレポートによると、音声認識デバイスの市場競争が激化していることが明らかになりました。',
        'subdescription': '音声認識機能は新しいコンセプトではありませんが、人工知能 (AI) とマシンラーニングの進歩により、近年採用される機会が増えています。アドビが公開したAdobe Digital Insights (ADI) の最新のレポートによると、音声認識デバイスの市場競争が激化していることが明らかになりました。',
        'document': 'http://blogs.adobe.com/adobemarketingcloudjapan/2017/07/11/adi-voice-report/',
        'iconUrl': 'http://blogs.adobe.com/adobemarketingcloudjapan/files/2017/07/1046x616_Voice-Assistants-Are-Poised-To-Be-The-Next-Tech-Disruptor-Static-1024x603.jpg'
      }])

  def test_jsonfeed_to_activities_author_not_dict(self):
    """Based on output from https://rss2json.com/

    https://console.cloud.google.com/errors/detail/COO65cat_4niTQ?project=granary-demo
    """
    with self.assertRaises(ValueError):
      jsonfeed_to_activities({'items': [{'author': 'Ms. Foo'}]})

  def test_activities_to_jsonfeed_author_not_dict(self):
    """https://console.cloud.google.com/errors/detail/CN-yh-3M7crdLA;time=P30D?project=granary-demo"""
    self.assertEqual({
      'version': 'https://jsonfeed.org/version/1',
      'title': 'JSON Feed',
      'items': [{
        'content_text': '',
      }],
    }, activities_to_jsonfeed([{
      'author': 'http://foo',
    }]))

  def test_convert_newlines_to_brs(self):
    """https://github.com/snarfed/granary/issues/456"""
    got = activities_to_jsonfeed([{
      'content': 'foo\nbar\nbaz',
    }])
    self.assert_equals("""\
foo<br />
bar<br />
baz
""", got['items'][0]['content_html'])
