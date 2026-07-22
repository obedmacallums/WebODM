PluginsAPI.Map.willAddControls([
    	'viewshed/build/Viewshed.js',
    	'viewshed/build/Viewshed.css'
	], function(args, Viewshed){
	var tasks = [];
	var ids = {};

	for (var i = 0; i < args.tiles.length; i++){
		var task = args.tiles[i].meta.task;
		if (!ids[task.id]){
			tasks.push(task);
			ids[task.id] = true;
		}
	}

	if (tasks.length === 1){
		args.map.addControl(new Viewshed({map: args.map, tasks: tasks}));
	}
});
