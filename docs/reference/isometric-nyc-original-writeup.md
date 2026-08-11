# Isometric NYC — Original Write-up (cannoneyed)

> Source: cannoneyed's essay on isometric.nyc. Preserved verbatim (minus site navigation)
> for reference. Our project adapts this approach to arbitrary cities, starting with
> Toronto, Canada. See `../pipeline-breakdown.md` for the distilled methodology.

---

A few months ago I was standing on the 13th floor balcony of the Google New York 9th St office staring out at Lower Manhattan. I'd been deep in the weeds of a secret project using Nano Banana and Veo and was thinking deeply about what these new models mean for the future of creativity.

I find the usual conversations about AI and creativity to be pretty boring - we've been talking about cameras and sampling for years now, and I'm not particularly interested in getting mired down in the muck of the morality and economics of it all. I'm really only interested in one question:

What's possible now that was impossible before?

## The Idea

Growing up, I played a lot of video games, and my favorites were world building games like SimCity 2000 and Rollercoaster Tycoon. As a core millennial rapidly approaching middle age, I'm a sucker for the nostalgic vibes of those late 90s / early 2000s games. As I stared out at the city, I couldn't help but imagine what it would look like in the style of those childhood memories.

So here's the idea: I'm going to make a giant isometric pixel-art map of New York City. And I'm going to use it as an excuse to push hard on the limits of the latest and greatest generative models and coding agents.

Best case scenario, I'll make something cool, and worst case scenario, I'll learn a lot.

> 📒 Note - From here on out I'll refer to all AI coding tools collectively as the "agent" - I switched back and forth a lot between Claude Code, Gemini CLI, and Cursor (using both Opus 4.5 and Gemini 3 Pro) and as far as I'm concerned they all worked pretty well.

## The Process

I'm going to lead with my biggest takeaway: I wound up writing almost no code for this project. I couldn't have picked a better time to start this project - the release of Gemini 3 and Opus 4.5 along with the maturing platforms of Cursor and Claude Code marked a true inflection point for the craft of software.

I'd been deep into agentic coding for the past few years and I've had to dramatically recalibrate my understanding of software after this project.

But before there was a single line of code there was an idea, and it went something like this:

Let's use Nano Banana to generate a pixel art map from satellite imagery tile-by-tile.

And so I started this project as I start almost every project now - by asking Gemini.

> 💭 A brief aside - One of my favorite ways to use AI is simply performing tasks at a scale that were previously impossible. Napoleon may have once said "quantity has a quality all its own". As a former electronic musician who's spent at least 10,000 hours precisely moving around audio clips, I'm particularly interested in scaling up the grindy repetitive tasks that make many ideas practically impossible.

## NYC City Data

My initial strategy was to use 3D CityGML data from a variety of sources to render a "whitebox" view of individual tiles. I found a few sources (NYC 3D, 3DCityDB, NYC CityGML), downloaded some data, and then set cursor up to build out a renderer. And very quickly I had something that worked pretty well.

I can't stress how big of a deal this is - I've never worked with CityGML data before and GIS is notoriously finicky and complex. With a lot of back and forth with the agent correcting for coordinate projection systems and geometry labeling schema, I was pretty quickly able to get a renderer set up that could output an isometric (orthographic) render of real city geometry superimposed on a satellite image.

*(image: whitebox render of city geometry plus satellite texture)*

I quickly set up a marimo notebook to start testing out my plan with Nano Banana Pro and discovered a number of issues. Long story short, there was a bit too much inconsistency between the "whitebox" geometry and the top-down satellite imagery, and Nano Banana was prone to too much hallucination in resolving these differences.

So I started digging again (in consultation with Gemini), and it turns out the Google Maps 3D tiles API is basically exactly what I needed - precise geometry and textures in one renderer. Of course, I needed a way to download the geometry for a precise tile, render it in a web renderer (using an orthographic camera) and export those tiles precisely matched with the existing whitebox renders. And sure enough, with a bit of back and forth, the agent was able to build it for me.

*(task doc: tasks/004_tiles.md)*
*(image: isometric web render of city geometry from Google Maps 3D tiles)*

## Image Generation

After a bit of prompt hacking, I was able to get Nano Banana Pro to generate tiles in my preferred style fairly reliably.

*(image: generated pixel art image from Nano Banana Pro)*

But generating image assets with Nano Banana has a few big issues:

- **Consistency:** Even with reference images, examples, and tons of prompt engineering, Nano Banana still struggles mightily to generate images with the preferred style consistently. I'd guess that it's at best 50/50, which is far from good enough for the estimated 40k tiles I'll need to generate.
- **Cost & Speed:** Simply put, Nano Banana is slow and quite expensive. It simply won't be possible to generate all of the tiles I'll need to generate given the cost and speed of a powerful model.

So I decided to fine-tune a smaller, faster, cheaper model. I opted to try fine-tuning a Qwen/Image-Edit model on the (wonderful) oxen.ai service and created a training dataset of ~40 input/output pairs. The fine-tuning took ~4 hours and cost ~12 bucks, and I was pretty happy with the results!

*(image: input/output pairs for fine-tuning Qwen/Image-Edit)*
*(task doc: tasks/005_oxen_api.md)*

## Infill

Knowing that the Qwen/Image-Edit model can learn to generate tiles in the preferred style, I then began to plan the approach to generating all of the tiles. Because all tiles must be seamless, I decided to implement an "infill" strategy - rather than simply going from full 1024x1024 web render → generated pixel art tile, we created a dataset with input images that have a certain percentage of the target generated image "masked" out. This way we can "stagger" generation by generating the tile content adjacent to already-generated tiles. And once again, it seemed like Qwen/Image-Edit was able to learn this task.

*(image: infill pair images / diagram)*
*(task docs: tasks/006_infill_dataset.md, tasks/009_inpainting.md, tasks/010_omni_generation_dataset.md)*

## Generation

Even if you're not writing code by hand, it's critical to follow software engineering best practices - and in fact, because code is so cheap/fast, it's easier than ever to. This is probably worth its own essay, but in short:

- Make small, isolated changes and test them
- Domain modeling and data storage are critical
- Simple and boring tech is better
- Iteration is better than up-front design

Keeping this in mind, I opted to design an end-to-end generation application to facilitate the process of generating the tiles. Experience shows that you'll hit edge cases and hit them fast (and oh did I), so it's good practice to start small before scaling things up. I whipped up a spec and had the agent generate a simple system for driving generation:

- A schema centered around 512x512 pixel "quadrants", with a given model call generating a 2x2 quadrant image from an input with a mask.
- A Sqlite database to store all quadrants along with their coordinates + optional metadata
- A web application for displaying the generated quadrants and selecting quadrants to generate.

*(task docs: tasks/007_e2e_generation.md, tasks/008_e2e_generation_pixels.md, tasks/012_generation_rules.md, tasks/013_generation_app.md)*

And lo and behold, with a bit of back-and-forth I had a working web application for progressively generating tile data.

## Micro-tools

Everyone who's built software before AI knows the feeling of needing a tool to make it easier to analyze or debug some part of the system. You stop what you're doing and get ready to hammer something out, and realize that it's a much more thorny problem than you'd thought. You dig a bit deeper and accept that it'll take hours or days or weeks to build, and you go back to the main task dejected. Maybe you file a todo that you know deep down will never get done.

AI agents change everything. Any micro-tool you can imagine is just a few instructions away. Hell, the agent can even build it in a background thread in an isolated work branch. And it'll be done in minutes.

I built a wide variety of these micro-tools across the application. Here are a few off the top of my head:

- **Bounds app** to visualize generated/in-progress tiles superimposed on a real map of NYC. Eventually this evolved into a full-fledged boundary polygon editor to determine the edges of the final exported tiles
- **Water classifier** to classify whether or not a given quadrant partially or completely contained water.
- **Training data generator** to generate training data for the Qwen/Image-Edit model.

*(task doc: tasks/014_bounds_app.md)*
*(image: debug map showing the tiles that have been generated)*

A pattern that I've noticed when building out this set of tools is something like the following:

**CLI tool → Library → Application**

CLI tools are very easy for the agent to use, test, and debug. They also encourage simple boundaries and discourage tight coupling. When the time comes to integrate them into a bigger system or application, it's trivial to ask the agent to abstract the functionality into a shared library.

## Edge Cases

Everyone who's worked in software knows the feeling: you've just built the killer tool that's going to solve all your problems. You've thrown a bunch of test cases at it and it just keeps working, and you're certain that you're 90% done with the project. And then you hit an edge case, and realize, once again, that the last 10% of the work takes 90% of the time.

There were too many edge cases to give justice to here, but I'll focus on two particular issues that caused a lot of downstream challenges: water and trees.

See, New York City has a lot of water - the Hudson and East Rivers empty into the New York Harbor and Bay, and Jamaica Bay and the Long Island Sound are both large bodies of water with lots of marine topography like islands, sand bars, and marshlands.

I'd not anticipated both the shear amount of water I'd be need to generate and, more importantly, how difficult it would be for my fine-tuned models to handle this.

*(image: water and trees caused lots of issues for the models)*

As a brief aside, fine-tuning models is hard. In particular, image models have a lot of quirks that make it very difficult to handle certain tasks - separating structure from texture is a classic issue.

No matter what I did to retrain my fine-tuned image models, I couldn't get them to reliably generate water. And trees were much worse - almost a perfect pathological use case for these models.

At some point in almost every creative AI project, you hit a point where the models just can't do what you need them to. You'll need to deploy your own intelligence and grind through these edge cases, and at this point it becomes imperative to use tools to make it as easy and consistent as possible. Fortunately, we live in an age where an agent can build you almost any tool you can imagine.

I built a number of micro-tools to help make this work easier, including:

- Automatic color-picker based water correction in the generation app
- Custom prompting + negative prompting and model-swappability for running generation
- Export/import to/from Affinity (photo editing software) for the most manual fixes

But at the end of the day, the last 10% always takes up 90% of the time and, as always, the difference between good enough and great is the amount of love you put into the work. So in the end, I rolled up my sleeves and threw a lot of time into manually fixing these edge cases.

*(task doc: tasks/018_water_fix.md)*

## Scaling up

Oxen.ai is a wonderful service - automating and abstracting away all of the fiddly bits of fine-tuning and deploying models and managing training data. But inference through the platform was rather expensive and rather slow - if I wanted to scale up the process to generate all of the NYC map we'd need to make the models significantly faster (or more parallelizable) and cheaper.

So I opted to export the weights from Oxen to my own rented GPU+VMs using Lambda AI (another fantastic service). I've been training and deploying models for a long time, and I remember the horrors of getting models to run on commodity hardware. But add this process to the long list of things that AI coding agents magically solve.

I simply booted up a VM with an H100, ssh'd into it with Cursor, and prompted the agent to set up an inference server that I could ping from my web generation app. What used to take hours or days of painful, slow debugging now takes literally minutes.

Now I could run n models in parallel and generate large spans of the map. Every night, I'd spend a few minutes setting up a plan for which tiles to generate and then let the models run overnight. For less than $3 an hour and more than 200 generations/hour, the project became tractable both in terms of time and cost.

Of course, now I needed to build a lot of tooling to manage this scale, including retry logic, parallel model queues, and tile planning infrastructure, but the agents took care of this as easily as anything else.

> 💭 Again, software engineering doesn't go away in the age of AI - it just moves up the ladder of abstraction. I still had to spec out the behavior of the generation queues and logic which incorporated all of the subtle domain-specific logic, but I no longer cared about any of the code that implemented it. I'm serious - I've never even looked at it.

## Automating

Now that I'd scaled up generation and addressed some of the edge cases, I set off to automate as much of the work as I could. Unfortunately, this is where the project (and the models) failed the hardest.

Interestingly, it was extremely difficult to get the agents to implement and understand an efficient tiling algorithm. The rules for generation are fairly simple - no quadrant may be generated such that a "seam" will be present.

*(image: a sample of tile generation rules to avoid seams)*

But despite the simplicity of the constraint, it was very difficult to specify the generation logic, test that logic, and then make it useful by higher-level planning / optimization algorithms. All in all, I did a lot of iterating here and spent a lot of fruitless efforts at getting the agent to understand how to build a planning algorithm. But after a lot of attempts and iterations, I eventually wound up with something that worked well enough with a bit of manual guidance.

One takeaway is that some algorithms are irreducibly complex, and it can still be very difficult to get these otherwise extremely smart models to understand the core logic behind them via the crappy medium of specification documents and instructions.

*(task docs: 015_automatic_generation.md, 016_generation_playbook.md, 019_strip_plan.md)*

Once I got the app to reliably generate "plans" for large spans of the map, I kicked off a large batch of generations and ran them overnight. The results were mostly good, but the model still demonstrated a number of failure modes (especially around water and terrain).

In a perfect world, I'd add some kind of AI review process to ensure that the generations were up to par. But in most cases, even the smartest image models like Gemini 3 pro couldn't reliably assess most of the failure modes (such as seams and incorrect tree generation). And even when the model could assess these issues, there was no way to deploy it reliably at a scale and speed that wouldn't make the process intractable.

So I wound up accepting that I'd simply need to put in the effort to manually review, flag, and correct the generations across the map. And while it did take a lot of work (way more than I'd planned to spend on the project), the AI agents' ability to build custom bespoke micro-tools to make it easier proved invaluable.

## The app

Now that the tile generation process was humming along nicely, I wanted to build out the final application to display the generated tiles at all of the zoom levels. This seemed like it would be simple, but wound up being one of the more difficult tasks for the coding agents to handle.

By a stroke of luck, I spent my first year at Google Brain building a custom tiled gigapixel image viewer, so I intimately know the challenges in the problem space. And while I opted to use the open source OpenSeaDragon library, I had to rely on my expertise for countless zoom/coordinate space and caching/performance issues that arose. This kind of app in particular seems like a very pathological challenge for today's generation of coding agents - high performance graphics with a lot of manual touch interaction are not handled very well by any of the browser control tools.

But after quite a bit of debugging I was able to get the app up, running, and deployed.

## Takeaways

### Cheap, fast software

The biggest joy of this project was the ability to build tools at the speed of thought. As a software developer, I think of a million little tools I'd like to have but would take a day or a week to build. With Claude or Cursor, I can whip them up in 5 minutes. This is absolutely transformational - it's like having an infinite toolbox.

Of course, software engineering rules still apply. Entropy is everything; as you add features, complexity grows, and without architecture, you accumulate tech debt. But here's the thing: for throwaway tools—debuggers, visualizers, script runners—code quality doesn't really matter.

I know how crappy the code for my generation app is. It's a mess of imperative JavaScript and spaghetti event listeners that I'd never write by hand. But it's not going out to customers. It doesn't need to scale. I'm the only user, and the bugs are tolerable given how little it cost me. The fact that it is cheap and fast more than makes up for the fact that it isn't all that great.

In general, composability is huge and even more valuable in the context of vibe coding. The Unix philosophy of small, modular programs that do one thing well means that we can easily compose smaller tools into utility functions that can be reused by higher-level applications. By designing pieces of functionality in a modular way, you can most effectively leverage the coding agent - it's easier for you to specify simple behavior, it's easier for the agent to build, debug, and test these modular pieces, and it's easier to stitch them together into higher level apps later on. This is standard software engineering best practices, and it's more relevant now that the cost of code is approaching zero.

### Image models aren't there yet

This project also highlighted a massive gap between text/code generation and image generation.

If I ask an agent to write software, it can run the code, read the stack trace, see the error, and correct itself. It has a tight feedback loop. It understands the system it is building.

Image models just aren't there yet. If you were managing a human artist, you could say, "Hey, make sure the trees are this specific style," and they would execute. While models can do this, they can't do it reliably. Even a model as smart as Gemini 3 Pro cannot reliably look at an output and say, "There is a seam here," or "This tree texture is wrong." Because they can't reliably "see" the failure modes, I couldn't automate the QA process. I had to give up on fully automated generation because the models simply couldn't understand their own mistakes.

Fine-tuning remains as flimsy as ever - anyone who's ever trained a model understands at a deep level that these are alien intelligences. Models often learn things in a deeply counterintuitive way, and in many cases you need to have a deep understanding of ML theory and strong intuitions about model implementations in order to reliably train them to accomplish the task at hand.

There's something fundamentally broken here - people are more than capable of contrastive learning (learning from their mistakes) and continuous learning (learning as they go) yet most AI agents are trained purely via association and are completely stateless. I'm optimistic that we'll make progress here, though it'll require some fundamental changes to our model architectures and training regimes.

These failure modes are especially apparent with image models - it might take you a minute to read and assess the output of a pdf extraction task, but you can see incorrect details in generated images in milliseconds.

### The edit problem

Finally, the interface for generative models is quite flimsy compared to text.

With code, I can point to a specific line. Because everything is text, prompts can be self-referential. With images, I can't reliably say, "Look at Image C and copy that tree." The model has no concept of "that tree." - I can't point to it and I can't reliably refer to it via text. It may not even know which image I mean by "Image C"

Even worse, it can't really edit the image. If I tell a coding agent to fix a bug, it modifies the file. If I tell an image model to fix a tree, it has to dream up the entire image from scratch again via diffusion. There is no reliable way to reach into the tokens and tweak just one variable.

There's no way to do basic instruction techniques like few-shot prompting, and there's no way to annotate images for editing. Masking doesn't exist, transparency doesn't exist. We're still so early in the evolution of generative image models, and while they can already do so much, we've got a long way to go.

### AI for artists

**The end of drudgery**

I spent a decade as an electronic musician, spending literally thousands of hours dragging little boxes around on a screen. So much of creative work is defined by this kind of tedious grind.

For example, after recording a multi-part vocal harmony you change something in the mix and now it feels like one of the phrases is off by 15 milliseconds. To fix it, you need to adjust every layer - and this gets more convoluted if you're using plugins or other processing on the material.

This isn't creative. It's just a slog. Every creative field - animation, video, software - is full of these tedious tasks. Of course, there's a case to be made that the very act of doing this manual work is what refines your instincts - but I think it's more of a "Just So" story than anything else. In the end, the quality of art is defined by the quality of your decisions - how much work you put into something is just a proxy for how much you care and how much you have to say.

**Unlocking Scale**

This project is far from perfect, but without generative models, it couldn't exist. There's simply no way to do this much work on your own, and hiring a team of artists large enough to hand-draw pixel art for every building in New York City would be impossible.

AI agents unlock a universe of creative projects that were previously unimaginable.

**Slop vs. Art**

If you can push a button and get content, then that content is a commodity. Its value is next to zero.

Counterintuitively, that's my biggest reason to be optimistic about AI and creativity. When hard parts become easy, the differentiator becomes love.

## Snow

To celebrate the wild winter we've had in the northeast, I decided it would be fun to add a "layer" to the map. I had no intention of going through the slog of generating an entire map by hand again, so I took all of the lessons learned from the first version of the map and set off to automate the process as much as possible. This of course entailed some boring refactors of the core project infrastructure, but at the core there were a few blocking issues that needed to be solved:

**1. Consistent generation, particularly in terms of color and style**

The number one issue with generating at scale is inconsistency between generations leading to drift across the map. This proves very difficult for the "infill" model to handle - without explicitly training the model to "blend" between adjacent quadrants with different colors/styles, the model will default to choosing one of the two contrasting styles, thus creating a scene.

The solution wound up being pretty simple: normalize the colors of all tiles used to train the models before generation, and normalize the colors in the "anchor" tiles after generation. The former is simple, but the latter is a bit more subtle - in order to properly balance the colors for the generated 2x2 quadrant tiles we need to ensure that water is ignored, since the water color.

*(image: a debug tool for ensuring generation consistency)*

**2. Fix generation issues, particularly for water and terrain**

One of the most consistent issues in generating tiles is water - image edit models are consistently unable to "understand" water, whether it's the "grainy" textures in a satellite render or the flat, plain color in an already-stylized tile. My hand-wavy explanation is that because the edit process can be thought of as adding noise to the input information and then denoising, a flat color is difficult to distinguish from pure noise from the perspective of the model and it thus tends to hallucinate random information on pure water tiles.

The strategy to solve this was twofold: First, we took the water mask system that we used in part 1 and used it to do two things - for the training data, all water was augmented with a 2x2 checkerboard grid pattern. This structured information was enough to allow the model to learn what water was and that it should be filled with a pure color. We also used the water mask to detect which tiles contained water, and use that mask to automatically "correct" the color of the water in those tiles (since the generation tended to have subtle color drift between generations).

We addressed the issue of terrain generation by pure data augmentation - training the model on a dataset that contained proportionally more water + terrain allowed the model to learn how to manage these features. This process was much more of an art than a science - I trained a number of variants with a number of different feature balances and still had to do a bit of manual correction after the generations were finished.

*(image: Left: the checkerboard pattern allowed the model to learn to generate water | Right: the model hallucinates random things on pure water tiles)*

**3. Dramatically increase throughput and decrease cost.**

One of the biggest bottlenecks for generating the v1 version of the map was GPU inference throughput. Thankfully, right around the time that I finished the first map I discovered the incredible modal.com service. I swear, I'm not a paid shill - but I can't say enough about the platform. Once you use it, the concept of serverless GPU inference is so obviously the future. Using modal, I was able to easily spin up 50 parallel instances of my fine-tuned Qwen/Image-Edit model and generate 10s of thousands of tiles in a few hours at very little cost. This meant that I could experiment much more rapidly, and essentially one-shot the entire map. At the end, it still required a few hours of manual clean up, but it's conceivable to add a bit more automation to check generations and essentially automate the entire process of map generation end-to-end.

*(image: a side-by-side of the automatic generation plan and in-progress tracking of generation)*

**Final takeaways**

Of course, what would a snowy map be without snow? And, just like everything else in the project, I was able to very easily create a snow shader (with a full debug tool for dialing in the settings) in a manner of minutes. It's worth saying it again and again, but it's truly never been a better time to be a builder. Any tool you can imagine can be built on-demand. I've argued elsewhere that this is the beginning of the Software Industrial Revolution, and it's fundamentally changing the nature of software.

One specific anecdote to illustrate this point: While building out the e2e generation scripts, I noticed that the coding agent had reimplemented all of the tiling logic (checking seams, creating optimal packing plans, etc) that had previously been built for the more manual generation app. This is a common pitfall with coding agents - they quite literally can't remember what they've built and can often go off the rails without quite a bit of hand-holding. But no problem: I'd get the agent to refactor the tiling logic into a separate, shared library, and even better, I'd rigorously test it to ensure that all of the bases were covered and it functioned exactly as I wanted it to. And of course, the agent was able to happily perform the task. But how could I verify that the library worked as intended? The agent wrote an exhaustive unit test suite, but now I was faced with looking at 1000s of lines of python unit tests that tried to explain their functionality with ASCII docstring diagrams - not exactly the best way of understanding the system!

So I did what I've found myself doing over and over again - I built a micro-tool - I asked the agent to add functionality to every test, such that when the test suite was run, it generates an image precisely illustrating the situation being tested and the result of the test. It used real data to illustrate what tiles had been already generated, what tiles were selected, and the image template that would be sent to the generative model (or error state). I then hosted these artifacts on a static debug html page and was able to quickly verify the intended behavior at a glance, a dramatically better situation than reading code line-by-line.

*(image: a pair of verification images generated by my tiling logic test suite)*

Others are discovering this same pattern too - from automatically creating gifs of new features to creating video overviews of pull requests, we're all discovering new patterns of how to build software along with new patterns of what software even is. I'd argue that we haven't really even internalized this new reality yet - literally our entire software engineering toolkit is designed around the core idea that teams of people write, debug, and review code by hand, and this world simply doesn't exist anymore. I believe that we're in the midst of a revolution of what computing even is, and as these models and systems continue to rapidly improve, we're going to realize that we need to fundamentally rethink the idea of computing. Scale your ambitions with your expectations, things are only going to move faster from here!
